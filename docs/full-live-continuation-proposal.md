# Full-live continuation: correct CDK asset references and finish the missing tests

## Status and exact decision

**Offline preparation only; new execution approval is required.** The approved
`full-live-v1` run at `870e350` passed 1,460 offline tests, all 66 Athena items and
the retail item containing all 36 questions. The parity update did not take effect:
the copied CDK manifest and asset manifest still referenced the retail template.
CDK reported no changes. The controller refused to accept the mismatched state,
timed out after 130.342 seconds and completed the approved restoration/smoke path.
No parity-agent test ran. This is a template asset metadata defect, not an IAM
failure or evidence of a transport problem.

The new proposed campaign is **`full-live-continuation-v1`**. It runs only the
missing **18 agent pytest items / 19 requests**, then restores accepted retail and
runs **one protected Q18 smoke**. No Athena or retail suite is repeated. This needs
**20 new Runtime invocations**, including the smoke. Prior usage is **37**, so the
aggregate maximum becomes **57**, **one more than the original approved 56**.
The new proposal does not reuse/reset the blocked parent ledger or any historical
milestone/UI allowance. No extra warm-up, demonstration, reserve or retry is included.

Review: [continuation.proposed.json](../evaluations/full-live/continuation.proposed.json),
SHA-256 **70161d5cb64bdc44f72a1cd61a3df614c53bdd879bb102e21a6c28dc07f0bc8a**.
Expiry remains **2026-11-13T23:59:00Z**, November 13 at **5:59 p.m. CST**. This is the
authorization cutoff for billable dispatch. It prevents an old saved approval from
permitting later calls indefinitely. Start requires four hours remaining and the
temporary update requires two hours for tests/restoration. Expiry blocks new calls,
including smoke, but does not block nonbillable restoration. Never extend it silently.

## Preserved actual checkpoint and correction

Fresh approved preflight and completed cleanup verified `analytics-dev`, account
`453711491609`, `us-west-2`, the existing Runtime and DEFAULT **READY v13**, runtime
stack **UPDATE_COMPLETE**. The final restored proof is dated **2026-11-11T18:20:29Z**;
this historical observation is not a substitute for the next fresh check. Retail
was already current, so restoration required no new mutation/version. Protected
smoke passed **110.25 USD [2025-03-31, 2025-04-01)**. Runtime attempts were **37/56**
(retail 36 + smoke 1); direct Athena submissions **67/201**; no failed/incomplete SDK
attempt. Parent dispatch is blocked by its spent restoration phase and durable claim.

[Committed checkpoint summary](../evaluations/full-live/checkpoint-2026-11-11.json)
binds the retained reports. Raw evidence is in
`artifacts/full-live/operations/approved-run-20261111/`. Parent preservation inventory:
`artifacts/full-live/verification/failed-run-preservation.json`, SHA
**5f60b2a02da1b0f84cb5872292382d92aa9e545831e3954a74aefa9984657dcb**,
pinning 134 files: ledger, reservations, SDK/attempt claims, review and run evidence.
The continuation verifies those bytes and the actual parent 37/67 accounting before
dispatch. The original preparation and failed attempt remain unchanged.

The source correction validates the template bytes, stack template URL, asset ID,
source path/packaging, destination bucket/key/region/role and dependency/file inventory
as one binding. It repairs only newly copied assembly metadata. Stale metadata is
now rejected before AWS clients or execution, even if an inventory is recomputed.
Cleanup validates the correct retail restoration independently of parity/source data.

New preparation: `artifacts/full-live/prepared-v2/`, inventory SHA
**8d1b2b88f933d80e7283019bcae5dcaeae8e3fb05fa622d665964ca3de249bd2**.
The only new assembly differences from the failed preparation are the parity
`manifest.json` template URL and the parity asset manifest's template hash/key.
The already reviewed parity template itself is unchanged:
**9b84152070e6e5babf4f2469abdde3a6e504d29c8887127a155f71ab871df83d**.
The retail template remains **faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368**.

## Deployment scope and immutable inputs

Use only the existing `analytics-dev` profile, account `453711491609`, region
`us-west-2`. Do not create profiles or inspect unavailable IAM policies again.
Administrator content-coverage evidence and its attachment/effective-access limits
remain in the shared UI runbook. No additional permissions are proposed.

- Existing Runtime: `enterprise_analytics_dev_agent-HlWywlG60h`, DEFAULT endpoint.
- Existing candidate SHA: `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1`.
- Existing S3 VersionId: `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu`.
- Model: `us.amazon.nova-lite-v1:0`, unchanged US routing and bounded loop.
- Temporary trusted configuration: `parity-v1`, tenant `t1`, reference date
  `2025-02-01`, North/South. Restore accepted `retail-v1`, `retail_demo`,
  `2025-04-01`, North/South using the same candidate archive/version.
- Normal CDK deployment publishes the corrected **CloudFormation template asset**
  `9b8415...json` to the existing bootstrap assets bucket. No code ZIP upload,
  rebuild, dataset publication, IAM/trust change or new resource is included.
- Preserve M3/foundation infrastructure, original/candidate archives, all source
  publications/goldens, historical ledgers/claims and PR #8. Keep new commits local.

## Offline preparation and proposed execution commands

Run from the repository root using the existing environment. Prepared outputs and
reports are immutable; execution requires new directories and explicit approval.

```sh
conda activate enterprise-analytics

# Already completed offline; do not overwrite this retained preparation.
poetry run python -m infrastructure.agentcore.full_live prepare \
  --output artifacts/full-live/prepared-v2

poetry run python -m infrastructure.agentcore.full_live_continuation verify-offline \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/verification/continuation-reviewed-offline.json

# Only after approval of this new scope and exact review.
poetry run python -m infrastructure.agentcore.full_live_continuation preflight \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/operations/continuation-approved-preflight

poetry run python -m infrastructure.agentcore.full_live_continuation run \
  --execute-approved \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/operations/continuation-approved-run
```

The operator acquires the existing global/deployment guards and one new durable
attempt claim. It freshly verifies identity, exact original starting candidate-retail
v13 configuration/template/parameters/artifact, both policies, retention, canonical
publication and process journal. It reruns offline tests without AWS, then deploys
the corrected parity assembly and requires full controller reconciliation. READY
alone and a successful CDK exit are insufficient.

Only after exact parity verification, run the 18 unchanged parity items: 17 authored
questions plus both shared-session requests. Reserve every SDK dispatch first,
disable automatic Runtime retries and stop on a failed selected item. An unexpected
skip, missing configuration or a smaller selected suite fails acceptance. The final
new slot is exclusively reserved for restoration; both old/new counters stay durable.

Mandatory `finally` restores accepted candidate-retail after any attempted parity
deployment, including failures/interruption. Verify exact templates/parameters,
artifact/configuration, both policies, READY Runtime/DEFAULT and UPDATE_COMPLETE.
Record actual resulting versions, then judge protected Q18's complete request and
**110.25 USD [2025-03-31,2025-04-01)** result. No future version number is guessed.

For interrupted cleanup only, inspect retained claims/controller/process evidence
first; never overlap deployments or retry the ordinary run. Then, within this same
approved scope:

```sh
poetry run python -m infrastructure.agentcore.full_live_continuation restore \
  --execute-approved \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/operations/continuation-approved-restoration
```

Unknown/corrupt accounting blocks billable smoke, but not nonbillable restoration.
Keep original errors and restoration errors separately. Stop on drift/denial and
capture the complete operation-level failure; do not broaden permissions, mutate a
review, reset a counter or automatically start another attempt.

## Acceptance and remaining approval

Combine the pinned parent results (66 Athena + one 36-case retail item) with all
18 distinct new agent items to establish **85 live pytest items actually passed**,
zero selected skips. All current offline tests must pass too. Require all independent
request/result/version/authorization/session judgments, complete token/latency/scan
diagnostics, exact restored-retail proof and protected smoke. Parent validation
remains incomplete until these gates pass; existing M1–M5/UI evidence stays intact.

The new allowance covers **20 Runtime attempts**, no direct Athena submissions,
at most **57 aggregate Runtime calls** including prior 37, within the same expiry.
Runtime-internal model/tool/Athena activity remains under existing bounded controls
and must appear in diagnostics; the allowance is not a fixed dollar ceiling.
Billable failures/uncertain outcomes remain spent. No reserve or replay is proposed.

**Required decision: approve this exact corrected assembly/review, two existing
Runtime configuration updates, 20 new calls and the one-call increase to aggregate 57.**
The earlier approval at `870e350` does not cover that increase or reopen its ledger.

Official CDK references checked November 11, 2026:
[stack template asset URL](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.cloud_assembly_schema.AwsCloudFormationStackProperties.html?lang=python),
[asset manifest source/destinations](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.cloud_assembly_schema/AssetManifest.html).
