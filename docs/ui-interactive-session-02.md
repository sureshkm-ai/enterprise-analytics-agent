# Interactive Workbench session 02

## Readiness and approval

The merge-status closeout is complete. [PR #8](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/8)
merged on November 11, 2026 at `e22287538e22e1917eb2a21efbeadc4cec5c6d75`.
[PR #9](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/9) merged the
full validation on the same date at `1dfd788a9b773fbf8abd39a554033cccd683c4ee`.
[Main CI 43100659276](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43100659276)
passed for that exact merge: 1,570 offline tests, zero skips, lint, formatting, types
and both offline syntheses. The 85 live items passed separately in the completed
approved campaigns; this session does not rerun that acceptance or spend those ledgers.

The new interactive session is **prepared and freshly verified read-only, with
billable execution awaiting explicit approval of the scope below**. No application,
infrastructure, deployment, IAM or ZIP change is needed. No model/Runtime invocation,
Athena query, upload, publication or new live ledger has occurred in preparation.

Review: [interactive-02.proposed.json](../evaluations/ui-shared/interactive-02.proposed.json).
Validated review SHA-256:
**385f936a719ca17ee09fe4c62af7d7153d04e8cc9d6ee3e2aaf7bd7defa8bbc8**.
Campaign: **`ui-shared-retail-v1-02`**. Existing campaign files are immutable.

## Concrete proposed allowance

Approve **19 usable question attempts total**, shared across both billable modes:

- **1 AWS Q18 verification**, run by the operator before either UI agent mode opens.
- **18 interactive questions total**, chosen/submitted by the user in Local agent
  or AWS AgentCore mode. Switching modes does not create another allowance.
- The existing schema has a **20-slot ceiling**. Its final slot is reserved for
  original-parity rollback smoke and is **not approved or usable in this session**.
  It is not a retail health check, retry, demonstration or nineteenth regular question.

Expiry: **2026-11-13T23:59:00Z**, November 13, 2026 at **5:59 p.m. CST**. This is
the cutoff for starting billable dispatch, not a right to replay spent questions.
Expiry, failure/unknown outcome, or exhaustion blocks further calls. No automatic
invocation retry, allowance reset, silent extension or ordinary reserve use.

Only use existing `analytics-dev`, account **453711491609**, region **us-west-2**.
Model **us.amazon.nova-lite-v1:0**, including its existing US routing. Trusted scope:
`retail_demo`, North/South, dataset `retail-v1`, reference date **2025-04-01**.
The four semantic tools, v2 requests, exact numeric rendering and all five metrics
remain unchanged. Browser/model text cannot set identity, scope or configuration.

Local agent calls Bedrock and DuckDB; AWS AgentCore calls the deployed agent using
Athena. Each Local question can perform at most six Converse SDK attempts; each AWS
question permits one Runtime dispatch, whose existing model/tool/token/deadline/scan
limits still apply. Thus the interactive mix can use at most 108 direct Converse
attempts if all 18 regular questions are local, or 19 Runtime attempts if all are AWS
(including Q18). These are attempt limits, not a fixed dollar ceiling. Actual SDK
attempts, failures, tokens, latency and scans remain recorded. No extra warm-up or
automated ordinary demonstrations are included.

## Fresh release proof

Read-only preflight at **2026-11-11T21:26:03.819419Z** verified:

- The selected caller/account and region; Runtime/DEFAULT **READY v15**, stack
  UPDATE_COMPLETE, fixed tenant/region/model/reference-date settings.
- Full templates/parameters, both resource policies, seven-day log retention and
  retained M3/foundation state; no denied IAM inspection was repeated.
- All **25** shared source files, locked dependency versions, the actual frozen
  candidate ZIP/object/version and configuration, plus canonical retail publication
  bytes/local provenance, latest S3 identities, exclusive prefixes and Glue bindings.

| Binding | Verified value |
| --- | --- |
| Runtime | `enterprise_analytics_dev_agent-HlWywlG60h`, `DEFAULT`, v15 |
| ZIP SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| Existing S3 VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` |
| Shared source SHA-256 | `aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be` |
| Runtime configuration SHA-256 | `6f480b57d00cb5386556ec4c2d3ff5618dc6e0e51a9147577fbd730c8d764c4e` |
| Retail template SHA-256 | `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` |
| Canonical manifest SHA-256 | `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797` |
| New release-record SHA-256 | `3908c11e5de25907451e0cc382afe54260b2a1d41a517438003e719449630ebe` |
| Full preflight SHA-256 | `59d83c0c8f863df5800440b92c6b74975b9c23209cfecf969ba5aed32b98bfa8` |

Retained preparation: `artifacts/ui-shared/interactive-02-preparation/` contains
`preflight.json`, its read journal, `release-record.json`, offline/readiness proofs
and a preservation inventory. The release record was extracted unchanged from the
validated fresh preflight record, not made by changing the old v13 record/version.
Its observation is historical after this preparation; each new question rechecks
AWS and refuses a version/configuration/source/publication mismatch before dispatch.

Existing administrator policy-content evidence covers the requested model and
candidate-key actions. Attachment/effective-policy inspection limitations remain
[as documented](ui-shared-code-live.md#administrator-console-policy-review--november-11-2026).
No duplicate grant or permission change is proposed. An actual denied call stops
the session with diagnostics; it is not a reason for speculative IAM expansion.

## Completed preparation and checks

From the repository root in the existing `enterprise-analytics` Conda environment:

```sh
# Already completed read-only; preserve this output and its journal.
poetry run python -m infrastructure.agentcore.ui_workflow preflight \
  --kind candidate \
  --review evaluations/ui-shared/interactive-02.proposed.json \
  --output artifacts/ui-shared/interactive-02-preparation/preflight.json

poetry check --lock
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests
```

Actual results: lockfile passed; **1,570 passed, 85 deselected in 55.45s, zero skipped**;
Ruff lint passed; **161** files formatted; mypy **127** source files passed.
The 85 live tests were not rerun. Existing merged infrastructure/source is unchanged;
main CI already verified both offline syntheses. New configuration assertions prove
only campaign/expiry differ from the accepted review, the new record binds v15 and
the new review, both UI agent modes stay disabled before verification, and offline
construction/status create no AWS session or campaign ledger. Historical ledgers,
artifacts, source/data/goldens and claims remain unchanged.

## Activation commands — only after approval

Do not run these billable commands until this exact scope/review is approved. The
operator performs only the fixed Q18 verification; the user owns all regular UI
submissions. One loopback UI process/user at a time.

```sh
conda activate enterprise-analytics

# One counted AWS call; requires full Q18 plan/value before UI agent modes open.
poetry run python -m enterprise_analytics_agent.adapters.ui_shared \
  --purpose verification --invoke-live \
  --review evaluations/ui-shared/interactive-02.proposed.json \
  --release-record artifacts/ui-shared/interactive-02-preparation/release-record.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
  --output artifacts/ui-shared/interactive-02-preparation/verification.json

# After Q18 passes, this launch itself makes no model/Runtime call.
poetry run python -m enterprise_analytics_agent.ui \
  --allow-live \
  --shared-review evaluations/ui-shared/interactive-02.proposed.json \
  --release-record artifacts/ui-shared/interactive-02-preparation/release-record.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
  --report artifacts/ui-shared/replay-aws-agentcore.json \
  --port 8501
```

Open **http://127.0.0.1:8501**. Choose Local agent or AWS AgentCore after reading
the billable notice. For example, ask “Show net_revenue for January 2025 by region.”
Offline playground and Saved runs remain AWS-free and do not spend the allowance.
Closing/restarting the UI does not reset counters. Stop the server with **Ctrl+C**.
If your offline UI already occupies port 8501, stop it in its terminal first or use
`--port 8502`; do not terminate unrelated processes.

The Q18 gate requires the full `net_revenue` request for
**[2025-03-31,2025-04-01)** and independently expected **110.25 USD**, correct units,
versions, scope and diagnostics. On success, used 1/20, regular 18 remaining, protected
original-rollback 1 unavailable. After all 18 regular submissions, used 19/20 and
ordinary dispatch is blocked even though the protected slot remains unused.

## Failure and stop procedure

If preflight drifts/fails, Q18 fails, an SDK call fails/has an uncertain outcome,
expiry is reached, or regular slots are exhausted, stop ordinary dispatch. Preserve
the question/SDK journals, reservations, preflight and operation-level diagnostics
under `artifacts/ui-shared/ui-shared-retail-v1-02/`; never retry a billable request
or delete/edit the evidence to reopen it. A failure after reservation stays spent.
Read-only failure before reservation sends no model/Runtime call.

Stop the UI with Ctrl+C and retain candidate-retail v15. **No deployment occurred,
so this scope does not authorize original-parity rollback, a restoration deployment
or either rollback-smoke invocation.** The existing `rollback_smoke` purpose is
hard-bound to original parity and cannot be renamed/reused as retail verification.
If any resource restoration becomes necessary due to external drift, preserve its
evidence and obtain a separately reviewed decision before mutation.

Preserve all historical campaigns, including M4 28/40, original M5 38/40, Q18 repair
and continuation histories, recovery 38/38/aggregate 40/40, original UI 19/20 and full
validation continuation 20/20/aggregate 57/57. None funds this new proposal. No profile,
permission, code rebuild/upload, dataset mutation or further milestone is authorized.
