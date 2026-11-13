# Multi-model streaming workbench: exact execution proposal

Implementation **106b17309716d11f154c8954024f7a260c8fbf7a** is prepared on
`feat/bedrock-streaming-activation`; PR #13 stays unmerged. This is a **new**
workbench scope, not a replay of a failed campaign or reuse of the stale accepted-Nova
source binding. Packaging, offline verification and fresh read-only preflight are
complete. Upload, deployment and billable acceptance await the single approval below.

## Reviewed inputs and current state

| Input | Exact value |
|---|---|
| Profile / account / region | `analytics-dev` / `453711491609` / `us-west-2` |
| New campaign | `bedrock-stream-workbench-v1-01`, currently **0/40**, no claim or dispatch |
| Review | `evaluations/bedrock-streaming/review.workbench.proposed.json` |
| Review semantic SHA-256 | `c17f1bb9a7c3a29620c42bcf1a0217298a2fd6b0d473b9fcce7608ca90d247b3` |
| Preparation | `evaluations/bedrock-streaming/workbench.preparation.json`, **241 pinned inputs** |
| Preparation file SHA-256 | `195fb2033f92458ff6548e9e1aeb1b7e0a0dc0aa7c59de053e260ac7714a4d32` |
| Current source SHA-256 | `8ee90d63f5af4fa62b8e82f9525a9b6eca6d6d58fd6693aa023031283fe2224e` |
| New ZIP | `artifacts/bedrock-streaming/workbench-fix/candidate/agent.zip` |
| ZIP SHA-256 / bytes | `f2755c33d5bbbef44d834628b974c1c71b7313374c9e7835b4b7ce66238a2a6a` / **39,321,518** |
| Conditional upload key | `releases/f2755c33d5bbbef44d834628b974c1c71b7313374c9e7835b4b7ce66238a2a6a/agent.zip` |
| New S3 VersionId | **Not uploaded; unbound.** Record and verify the actual upload response; never guess it. |
| Candidate assembly | `artifacts/bedrock-streaming/workbench-fix/cdk.proposed.out` |
| Original restoration assembly | `artifacts/bedrock-streaming/workbench-fix/cdk.restoration.out` |
| Original streaming ZIP / actual S3 VersionId | `c136a3931e2af31d6453c54910ddc9e839ef03e69a6f2ddebb35b3eb7cfdc306` / `GSY36sTbDpCNZGogULTe3cBL__bujiQK` |
| Canonical manifest | `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797` |
| Expiry | **November 15, 2026, 5:59 p.m. CST**, `2026-11-15T23:59:00Z` |

Fresh `analytics-dev` STS verification identified the expected PowerUser SSO role
in account 453711491609. The full baseline capture and subsequent formal preflight
verified **all ten existing streaming stacks UPDATE_COMPLETE, Runtime/DEFAULT
READY v3**, exact original artifact/version/configuration/templates/parameters,
both resource policies, stack identities and execution role, and seven-day retention.
The retained legacy Nova target independently verified **READY v15**; canonical
S3/Glue publication matches the frozen retail inputs. Formal preflight completed
**2026-11-13T15:32:13Z**, including proof that the new candidate key does not exist.
These are new observations, separate from historical READY records.

Raw evidence: `artifacts/bedrock-streaming/workbench-fix/baseline-20261113T152900Z/`
and `artifacts/bedrock-streaming/workbench-fix/preflight-20261113T154100Z/`.
[Readiness](../evaluations/bedrock-streaming/workbench.readiness.json) records
their checksums and actual observations. Fresh preflight will run again inside
approved execution before mutation.

The current port-8501 listener is PID **13049**, launched with
`--accepted-runtime-review evaluations/ui-shared/accepted-nova-runtime.proposed.json`
and `--accepted-runtime-approval artifacts/ui-shared/accepted-nova-runtime/approval.json`.
Its actual API reports disabled because that old operator source pin no longer
matches 106b173. It is not a multi-model workbench. Keep it and its logs until
approved replacement; preserve the unrelated offline/saved-report servers on
ports 8510 and 8502.

## Exact changes requiring approval

1. Conditionally upload the reviewed ZIP **once**, with checksum, expected bucket
   owner and `IfNoneMatch=*`. Pin the actual returned VersionId and verify its
   version-specific bytes and current key binding. No overwrite or retry.
2. Update only the ten existing `enterprise-analytics-stream-*` stacks, one at a
   time, through the existing bounded controller. Reconcile exact template,
   parameters, Runtime/DEFAULT artifact/configuration/policies and readiness;
   READY alone cannot establish success.
3. Each stack changes only its runtime S3 code prefix/version, artifact checksum
   output and workload-role inline S3 read resources: the exact new key plus the
   exact original `c136a393…` key for restoration. The two independently synthesized
   assemblies reproduce **10 templates / 34 files byte-for-byte**. No model grant,
   principal, trust relationship, hosting setting, tenant/region scope or data-layer
   resource changes. Existing M3 permissions, query trust, administrator policies,
   retained code and all historical ledgers stay unchanged. No new IAM inspection
   or speculative Bedrock grant is required.
4. Run independent per-model AWS acceptance, then the actual browser checks below.
   On success leave usable candidate/retail targets deployed. Failing models stay
   clearly unavailable in both modes; partial acceptance is reported honestly.
   All ten updated targets may retain the candidate on partial success, but only
   passing, nonquarantined bindings can dispatch through the UI.

The ten fixed-model targets are Nova Lite, Claude Sonnet 5.5, Claude Opus 5.5,
GPT-6 Astra, GPT-6.1 Sol, Gemma 4 31B, Llama 4 Maverick, DeepSeek V3.2, Qwen3 235B
and Mistral Large 3. Exact identifiers, routes and allowed resources are in the
review/configuration. Google Gemma uses Bedrock Mantle; no direct provider API or
browser-supplied model ARN is introduced. The existing Sonnet denial is unresolved;
the new artifact retains private redacted full SDK errors for diagnosis. It does
not claim an IAM remedy or guarantee that model will pass.

## Attempt budget and acceptance

This is a separate **40-attempt outer cap**, with **38 ordinary slots**, one
protected original-restoration smoke and one **unapproved reserve**. No historical
allowance is reused. The reserve cannot be spent; at most 39 attempts are actually
authorized, including cleanup if necessary.

| Purpose | Maximum planned attempts |
|---|---:|
| AWS Q18 and all-five regional checks, once per model | 20 |
| Actual Local Bedrock/DuckDB browser Q18, once per AWS-accepted model | 10 |
| Actual AWS AgentCore browser Q18, one accepted model, preferring Nova | 1 |
| Ordinary user questions if all preceding models pass | 7 |
| Protected original-restoration smoke, failure only | 1 |
| Reserve, unavailable | 1 |

All 31 planned operator questions are charged before dispatch. There is no extra
warm-up: the first authored case exercises the cold path. A model failing Q18 does
not receive its all-five case or a Local browser test. Unused ordinary slots remain
within the same 38-slot cap and may be used by the user after successful browser
gates; they are not permission for retries or extra operator demonstrations.

Grade complete structured requests and results against the unchanged independent
goldens. Q18 must match **net revenue 110.25 USD**, exactly
**[2025-03-31, 2025-04-01)**. The other case covers all five metrics by region.
Require genuine provider words matching the independently recomputed readable
answer, valid terminal/usage events, exact decimals/units/dates, useful token/
latency/Athena diagnostics and no unsafe browser markup. In the browser, verify
model selection, composer clearing, readable partial output, final tables and
unavailable-model labels. Local uses canonical DuckDB; AWS uses Athena through
AgentCore, sharing the new presentation/tool code.

Completed errors, including durably recorded SDK transport failures, spend their
slot and quarantine that model; the receipt does not assert the remote operation
terminated. A separately authored check for a different fixed model may continue.
Never retry the failed invocation/model or substitute it automatically. Missing
or incomplete accounting, expiry, unexplained configuration drift or unresolved
deployment processes stop the whole workflow. A blocked model cannot be enabled
using `--model-testing`; that flag is not part of this proposal.

Costs are the selected models' tokens, AgentCore execution and Athena scans.
Each streaming question is bounded to six model operations and 12,000 combined
tokens; the original cleanup target retains its own reviewed bounds. Athena's
existing 10 MiB per-query limit remains unchanged. These controls are not a dollar
budget; rates differ by model. No subscription, data publication or new service is
part of this execution.

## Exact operator commands after approval

Use the existing Conda environment from this checkout:

```sh
conda activate enterprise-analytics
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/workbench.preparation.json verify-offline
```

Record the actual approval at
`artifacts/bedrock-streaming/workbench-fix/approval.json`, binding the review SHA,
preparation SHA, 40-attempt maximum and exact ISO expiry. No approval file exists
yet. Then execute the one reviewed operation:

```sh
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/workbench.preparation.json \
  execute --execute-approved \
  --approval artifacts/bedrock-streaming/workbench-fix/approval.json \
  --output artifacts/bedrock-streaming/workbench-fix/operations-approved-01
```

The operator writes `candidate-version.json`, exact update proofs, actual release
records and per-model acceptance reports. After usable AWS acceptance, replace
only the task-owned port-8501 server and launch with these **actual paths**:

```sh
poetry run python -m enterprise_analytics_agent.ui --port 8501 --allow-live \
  --streaming-review evaluations/bedrock-streaming/review.workbench.proposed.json \
  --streaming-releases artifacts/bedrock-streaming/workbench-fix/operations-approved-01/releases.actual.json \
  --streaming-approval artifacts/bedrock-streaming/workbench-fix/approval.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1
```

Open **http://127.0.0.1:8501/?mode=live**, then perform the counted browser checks.
The release file and approval do not exist before approved execution; this is a
prepared launch command, **not a claim the new live workbench is running yet**.

## Restoration and interruption

If deployment/accounting fails, no model passes, or the browser gates leave no
usable Local/AWS connection, stop ordinary dispatch and restore every attempted
stack to the exact original `c136a393…` artifact and real `GSY36…` S3 version using
the retained assembly. Do not restore the stale accepted-Nova source binding.
The legacy v15 Runtime is never redeployed; the single protected cleanup call
verifies its complete Q18 request/result and closes this campaign. Preserve all
failure logs, SDK errors, process journals and claims.

Automatic deployment/evaluation failure restoration is already in the controller.
For a later browser failure or interruption, inspect the operation/lease/process
journal first, wait for or reconcile the owned update, then use restoration only:

```sh
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/workbench.preparation.json \
  restore --execute-approved \
  --approval artifacts/bedrock-streaming/workbench-fix/approval.json \
  --operation artifacts/bedrock-streaming/workbench-fix/operations-approved-01 \
  --output artifacts/bedrock-streaming/workbench-fix/restoration-approved-01
```

No repeated upload, campaign reset or second smoke is allowed. The operator
requires at least **10 hours before expiry** when beginning deployment so bounded
updates/restoration can finish. If drift, denial or an unresolved process prevents
restoration, preserve the exact blocker; do not overlap updates, broaden IAM or
manufacture readiness. Keep failing choices disabled.

## Verification and references

Current baseline passed **2,165 offline tests, 85 deselected, zero selected skips**,
lockfile validation, Ruff, formatting (**208 files**) and mypy (**164 files**).
The two new syntheses reproduce exactly and permit only the changes listed above.
Both new-scope offline verification and formal read-only preflight passed at 0/40.
The retained project wheel is pinned at SHA-256
`13c7f43a95387a0def7315ad983fc6249722ee8be3b9ba53363e8bdadf19a991`.
Later documentation changes do not alter the verified 80-file runtime source.
To reproduce the exact archive after those changes, reuse that verified project
wheel with `--project-wheel artifacts/bedrock-streaming/workbench-fix/candidate/project-dist/enterprise_analytics_agent-0.1.0-py3-none-any.whl`
and the locked cached ARM64 wheels in a separate output directory; a fresh project
build embeds the current README in package metadata and is not the reviewed ZIP.
The preserved file inventory accounts for later legitimate Nova user activity:
that separate ledger is now 3/20, with 16 ordinary questions remaining; none is
borrowed by this proposal. Historical streaming counters remain closed at 3/40
and 4/37, aggregate 7/40.

Official references checked for this preparation:
[UpdateAgentRuntime](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/update_agent_runtime.html),
[conditional S3 PutObject and version response](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html),
[AgentCore JSON/SSE HTTP contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html).
