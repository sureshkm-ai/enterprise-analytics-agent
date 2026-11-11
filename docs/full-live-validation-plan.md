# Full test validation with no skipped tests

## Status and approval boundary

This records the original **`full-live-v1`** plan approved by the user at `870e350`
on November 11, 2026. It reused no completed UI or milestone allowance. Actual execution
passed offline 1,460, Athena 66 and retail 36, but stale copied parity CDK asset references
caused a no-change deployment. The controller refused acceptance;18 parity-agent
items remain unrun. Accepted-retail verification and protected smoke passed on
unchanged READY v13. Usage37/56 Runtime and 67/201 Athena, ordinary dispatch blocked.
See [the actual checkpoint](../evaluations/full-live/checkpoint-2026-11-11.json).

**Do not rerun this original campaign or alter its review/assemblies.** Its historical
preparation missed the asset-URL/file-asset references even though template bytes
were pinned. A [corrected continuation](full-live-continuation-proposal.md) is prepared
offline; it requires new approval for 20 calls, prior 37/aggregate 57. The plan below
preserves the original approved scope and failure/restoration procedure as evidence.

Use only `analytics-dev`, account `453711491609`, region `us-west-2`. Do not create
profiles, add permissions, upload/rebuild the code archive, publish datasets or modify
the M3 infrastructure. The administrator-supplied policy evidence and its attachment/
effective-access limitations remain recorded in [the UI policy review](ui-shared-code-live.md#administrator-console-policy-review--november-11-2026).
Denied inspection is not a reason to add grants or repeat unavailable IAM queries.

The accepted starting checkpoint is the separately approved candidate/retail release:
Runtime and DEFAULT **READY v13**, runtime stack **UPDATE_COMPLETE**, last observed
November 11, 2026, at 16:58:11Z. A fresh exact check is required before later execution;
the historical observation alone is insufficient. Preserve [the completed UI evidence](../evaluations/ui-shared/acceptance-2026-11-11.json)
and PR #8. This proposal neither merges that PR nor reopens its regular allowance.

## What must actually execute

| Phase | Required tests | Execution work |
| --- | ---: | --- |
| Offline unit/contract/operator suites | All selected offline tests, including the new validation regressions | No AWS sessions or calls |
| Athena parity | **66** | **67** logical Athena queries normally: 64 literal parity cases, one v1 metric query and two dimension queries; missing-source/unauthorized cases fail before submission |
| Retail evaluation | **1 pytest item** | All **36** frozen questions/session requests against the independent retail goldens |
| AgentCore parity | **18** | 17 authored question cases plus one two-request session-isolation test: **19 Runtime invocations** |
| Protected restored-retail smoke | Separate completion gate | **1 Runtime invocation**, fully judged Q18 |

The three live pytest phases execute **85 items**, with no selected test skipped.
The direct Athena cases cover `parity-v1` (55), `parity-no-returns-v1` (5) and
`parity-legacy-v1` (4), plus the two unparameterized tests. Each adapter is compared
against literal expected results; adapter agreement alone is insufficient.

Ordinary CI stays offline. Its command explicitly selects offline tests rather than
pretending the live tests ran. Live acceptance is reported separately, with the exact
66 + 1 + 18 test totals. `--fail-on-skip` makes an unexpected selected-test skip a
failure. Missing configuration or an empty selected live suite must fail, not report
acceptance. The retail pytest item must also pass all 36 inner cases, including the
shared-session pair; an unrun or failed inner case fails the gate.

These counts refer to the existing default parity AgentCore test items. Additional
legacy/empty-source AgentCore parameter expansions are not included in this 85-item
campaign; those source distinctions are exercised directly by the Athena phase.
No coverage is relabeled as passed merely because a test was deselected.

## Separate budget and immutable pins

Review file: `evaluations/full-live/review.proposed.json`, review SHA-256
`bd3724d46181ec3e7b0181987c48d3a535ab4815d02897305cd36b7ba44d8845`. Approved expiry:
**2026-11-13T23:59:00Z**, November 13 at 5:59 p.m. CST. It bounds billable authorization,
prevents indefinite saved approval and retains cleanup margins. It neither permits
replay of a completed/blocked campaign nor prevents nonbillable restoration.
The original approved allowance was **56 Runtime attempts**:

- Retail suite: 36.
- AgentCore parity suite: 19.
- Protected restored-retail Q18 smoke: 1.

There is **no extra warm-up, demonstration, Runtime retry or reserve**. The first
retail question is a real judged test and consumes its normal allocation. Reserve
before dispatch; failures, exceptions and uncertain outcomes remain spent. Disable
automatic SDK invocation retries. The final smoke slot cannot be consumed by tests.

The direct Athena phase has a separate hard cap of **201 query submissions**:
67 logical executions × the existing maximum of three terminal-query attempts.
Submission accounting must precede every actual `StartQueryExecution` dispatch.
Idempotent handling of an uncertain submission must retain its original request token;
no new logical query may be invented merely because polling failed. This direct cap
does not include Athena queries made internally by the Runtime's semantic tools;
those remain subject to the existing bounded agent/tool/query controls and diagnostics.

| Pin | Required value |
| --- | --- |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/enterprise_analytics_dev_agent-HlWywlG60h` |
| Qualifier | `DEFAULT` |
| Candidate ZIP SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| Actual existing S3 VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` |
| Candidate key | `releases/398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1/agent.zip` |
| Accepted retail template SHA-256 | `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` |
| Accepted retail configuration SHA-256 | `6f480b57d00cb5386556ec4c2d3ff5618dc6e0e51a9147577fbd730c8d764c4e` |
| Temporary parity template SHA-256 | `9b84152070e6e5babf4f2469abdde3a6e504d29c8887127a155f71ab871df83d` |
| Temporary parity configuration SHA-256 | `67056f86738cdfec508a9c00cd99c42767a8360b417c31928eb626eca3e530b3` |
| Common source fingerprint | `aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be` |
| Canonical retail manifest SHA-256 | `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797` |
| Existing M3 development configuration SHA-256 | `3297efb9f47e3b5eab48bd0da0675d1f05002900482a44e56832e215eeaef91a` |

The prepared parity template changes only trusted dataset/tenant/reference-date
configuration while preserving this exact candidate code/version. Its configuration
and assembly hashes, and the complete retail restoration inventory, are pinned by
the review/preparation records. **Review these exact hashes before approval.**
Neither configuration is the old original ZIP; successful cleanup restores the
currently accepted candidate retail release, not historical original/parity v12.
The pinned M3 configuration must retain `analytics-dev`, the approved account/region
and workgroup; offline verification rejects configuration drift before creating
clients, opening the new counter or inspecting source/publication readiness. Restoration
does not depend on this mutable configuration file.

All historical ledgers and claims remain immutable: M4 28/40; original M5 closed
38/40; repair 1/40; continuation 1/39; recovery closed 38/38, aggregate repair 40/40;
UI 19/20 with all 18 regular slots spent and its protected rollback unused. No old
allowance, unused remainder or claim can fund this proposal.

## Reviewed execution order

1. Acquire the existing global operator/deployment guards and the new campaign's
   durable attempt claim. Verify no task-owned deployment process is unresolved.
   Inspect the selected account using STS before other AWS operations.
2. Verify the exact starting **candidate/retail READY v13** checkpoint: code/version,
   complete template/parameters, trusted configuration, both resource policies,
   seven-day retention, source/dependency closure and actual retail S3/Glue bindings.
   Stop before mutation on drift,
   unavailable evidence, expired review or less than **four hours** remaining for
   the complete sequence and cleanup. Recheck before the temporary parity update;
   require at least **two hours** remaining for that phase and restoration.
3. Run the full offline selection with `--fail-on-skip`, then the **66 Athena tests**
   against the existing publications/workgroup. Its fixture loads each of the three
   ready parity manifests and verifies the workgroup, and its actual queries validate
   every source variant against literal independent results. This is not a claim of
   separate pre-query parity prefix/Glue inspection. Require independently expected
   values, no selected skips and the exact expected test count.
4. While the accepted retail configuration is still deployed, run the **one retail
   pytest item**, dispatching all **36** frozen requests through the newly bound
   trusted invocation context. Preserve per-case request/result/version/auth/session
   judgments, token/latency/scan diagnostics and failure/unrun denominators.
5. Update only the existing Runtime's trusted configuration to `parity-v1`, tenant
   `t1`, reference date `2025-02-01`, North/South, using the same candidate ZIP/version.
   Require bounded controller reconciliation with the exact parity template/parameters
   and full Runtime/DEFAULT proof. READY alone is insufficient.
6. Run all **18 AgentCore parity test items**, including both requests of the shared
   session test, using its reviewed generated configuration and new campaign counter.
7. In a mandatory `finally` path after any attempted parity update, restore the exact
   accepted **candidate/retail** code/configuration/template. Verify the resulting
   Runtime and DEFAULT are READY and the stack is UPDATE_COMPLETE. Record the actual
   new versions; never guess a future version or require the number 13 after an update.
8. Use the one protected smoke slot to require **110.25 USD** for
   **[2025-03-31, 2025-04-01)** with the complete Q18 request and retail versions/scope.
   Complete a final read-only checkpoint and combined zero-skip coverage/report audit.

The old retail pytest command cannot simply be rerun: its historical default runner
binds the original archive/checkpoint and a closed M5 ledger. The new operator context
is trusted configuration, not a model/browser argument, and supplies the reviewed
candidate checkpoint and separate counter. Preserve default historical behavior and
public contracts; do not replace old artifact constants to bypass those checks.
The old M4 wrapper also targets its historical ledger and must not be installed here.

## Preparation and execution commands

Run from the original repository root in the existing environment. All output paths
must be new; never overwrite previous evidence or create/reset a historical ledger.

```sh
conda activate enterprise-analytics

# Offline preparation command, already performed; do not overwrite its output.
poetry run python -m infrastructure.agentcore.full_live prepare \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/prepared

poetry run python -m infrastructure.agentcore.full_live verify-offline \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/verification/offline.json

# Read-only AWS preflight only after its execution scope is approved.
poetry run python -m infrastructure.agentcore.full_live preflight \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/operations/approved-preflight

# Approval required: the supervised full sequence, including mandatory cleanup.
poetry run python -m infrastructure.agentcore.full_live run --execute-approved \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/operations/approved-run
```

Preparation records include `artifacts/full-live/prepared/{retail,parity}`,
`agent.parity.json`, `retail.json` and `assembly-review.json`. Verify the CLI's actual
generated review/report hashes and source tree before approving execution. The run
command owns suite ordering, counting, controller proof reuse and cleanup; do not
manually run the same live pytest commands a second time to obtain another report.

## Failure, interruption and restoration-only recovery

Stop ordinary dispatch after a failed test, timeout, denial, unknown outcome, budget
failure, unexpected skip or checkpoint mismatch. Preserve the first failure and full
operation-level diagnostics; no automatic billable retry or speculative IAM expansion.
An interrupted/failed test is not a pass, and a restoration smoke does not repair its
acceptance result. Never overlap deployments or terminate unrelated processes.

After any attempted parity deployment, the accepted candidate-retail configuration
must be restored even if evaluation fails. Cleanup itself is nonbillable and is not
abandoned to save calls. Inspect the retained process journal, controller report and
attempt claim before resuming restoration. If the integrated workflow already restored
and verified retail, reuse that proof and actual version rather than redeploying again.

```sh
# Only for interrupted cleanup, after retained process/claim inspection.
poetry run python -m infrastructure.agentcore.full_live restore --execute-approved \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/operations/approved-restoration
```

Restoration-only recovery must preserve the same campaign and protected smoke slot;
it cannot reopen test dispatch. Expiry blocks new billable calls, including smoke,
but permits nonbillable restoration of the reviewed starting state. If a smoke cannot
run safely inside the window, record the incomplete gate and seek a new decision;
if accounting is unreadable or aliased, restore/verify the frozen configuration
without dispatching that smoke, retain the accounting and primary/restoration errors,
and report unknown usage rather than inventing a count or resetting the ledger.
Never extend the review or reset a counter. If failure occurs after retail Runtime
calls but before any parity mutation, freshly verify the retained retail checkpoint
and use the protected Q18 smoke without an unnecessary deployment. If failure occurs
in offline/Athena validation or retail setup before any Runtime call, stop without
spending that smoke slot. Preserve the starting proof and all diagnostic/counter
evidence; do not use the protected slot for an ordinary retry.

## Acceptance, evidence and cost limits

Acceptance requires all selected offline tests plus **66 + 1 + 18 live pytest items**
to pass with **zero selected skips**; all 36 retail inner requests and the shared
session pair must pass too. Require complete independent request/result judgments,
authorization/version evidence, exact typed values and final retail restoration/smoke.
No item is accepted by deselection, expected-failure masking or comparison with only
the other adapter. Preserve expected counts and fail if a suite silently shrinks.

Record the new campaign/review hash, tested Git commit, input/golden/publication hashes,
each durable Runtime/Athena reservation and outcome, pytest collection/results, model
configuration/tokens, latency, Athena bytes, controller stdout/stderr, full checkpoints,
observed versions and primary/restoration errors. Report offline readiness separately
from later live acceptance. Keep prior successful UI/M1–M5 evidence immutable.

Existing 10 MiB per-query scan limits, bounded Athena lifecycle, six agent iterations,
sixteen semantic tool calls, configured token/output limits and deadlines remain.
The new caps bound attempts, **not an aggregate dollar amount**. Runtime invocations
can perform multiple model/tool/Athena operations; those internal queries must be
included in actual usage reporting. No production load/concurrency, extra demo, warm-up,
reserve, additional service or next milestone is authorized by this plan.

The user approved this exact review/hash, expiry, configuration updates and
**56 Runtime / 201 direct Athena** caps. The actual partial run and mandatory cleanup
are recorded above. The remaining18 agent tests require the corrected continuation;
this historical approval does not increase the cap, reopen the parent or authorize
a further deployment/call. Full85-item acceptance is still incomplete.

References checked November 11, 2026: [pytest marker selection](https://docs.pytest.org/en/stable/how-to/mark.html), [pytest hooks](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_sessionfinish), [fixture resolution](https://docs.pytest.org/en/stable/how-to/fixtures.html#overriding-fixtures-at-various-levels).
