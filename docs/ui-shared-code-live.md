# Shared Bedrock agent: implementation and live proposal

## Status

Implemented in the original `feat/local-testing-ui` checkout based on `c6e6818`.
Administrator-supplied policy contents have been reviewed; deployment and billable
execution remain paused pending separate execution approval. Milestones 1–5 stay
complete; this is separately requested UI work.

| Mode | Implementation/data | AWS usage |
| --- | --- | --- |
| Offline playground | Deterministic planner, generated temporary sample, DuckDB | No SDK sessions or model calls |
| Local agent | Existing BedrockAnalyticsAgent, canonical retail Parquet, DuckDB | Billable Bedrock, analytics-dev |
| AWS AgentCore | Same class/catalog/v2 contracts/tools from accepted candidate, Athena | Billable Runtime, Bedrock, Athena |

Cost notices appear before submission. Both agent modes require a reviewed release,
allowance and successful counted Q18 verification. The offline sample is not canonical
retail. Browser fields cannot set identity, configuration, SQL, history or quota purpose.
AWS payloads remain question-only; authorization is fixed server-side.

## Actual source, artifact and data evidence

Preparation evidence: `artifacts/ui-shared/preparation/offline-release-audit.json`,
SHA `ae2e41af49661cc82a2fbf2f1f59e2f0eaf5ce3fa5bf07692902bfc9a64237f9`.

- All **25** inspected runtime/agent/DuckDB source files and the entrypoint match
  the accepted candidate. Source fingerprint:
  `aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be`.
  The audit rejects missing transitive modules, never executes/extracts ZIP code,
  excludes UI/operator modules and does not inspect dynamic imports.
- Original ZIP differs in `adapters/bedrock_agent.py` and `agent/questions.py`.
  Original-v12 cannot establish shared-core alignment. Reuse the matching candidate;
  no rebuild/upload is needed.
- All 13 runtime dependency versions match Conda, Poetry lock and frozen manifests.
  Wheel checksums and packaged bytes verify. macOS/Linux ARM64 native libraries are
  version-matched, not byte-identical platforms.
- Verified canonical retail rows: customers 48, products 24, orders 240, order_items
  480, payments 240, refunds 96, returns 40. Manifest SHA:
  `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797`.
  Hashes, sizes, schemas, immutable identifiers and all 36 frozen goldens match.

| Pin | Shared candidate | Original rollback |
| --- | --- | --- |
| ZIP SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` | `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` |
| S3 VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` | `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9` |
| Template SHA-256 | `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` | `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb` |
| Trusted config SHA-256 | `6f480b57d00cb5386556ec4c2d3ff5618dc6e0e51a9147577fbd730c8d764c4e` | `67056f86738cdfec508a9c00cd99c42767a8360b417c31928eb626eca3e530b3` |
| Dataset / tenant / reference date | retail-v1 / retail_demo / 2025-04-01 | parity-v1 / t1 / 2025-02-01 |

Both scopes allow North/South. Model `us.amazon.nova-lite-v1:0`: six iterations,
sixteen tools, 1,024 output tokens, 12,000 total tokens, 90-second scheduling limit.
The ZIP's embedded default is original; the reviewed environment override supplies
retail configuration. These distinct configuration hashes must not be confused.

## Read-only AWS preflight — November 10, 2026

Evidence: `artifacts/ui-shared/preflight/20261110T204310Z/` and the additional
`20261110T212343Z/publication-proof.json`. Explicit STS used only analytics-dev,
account 453711491609, us-west-2.

- Runtime/DEFAULT **READY v12**, runtime stack **UPDATE_COMPLETE**, original
  artifact/configuration, exact templates/complete parameters, both policies,
  seven-day retention and retained infrastructure/process guards verify.
- Candidate version-specific HEAD matches the accepted hash, size and VersionId.
- Fresh canonical downloads match frozen publication bytes. Eight latest HEADs,
  seven exact single-object prefix inventories and actual Glue schemas/locations/
  Parquet formats match. Later candidate operations/questions recheck these bindings.
- Nova Lite profile is ACTIVE and routes to US east-1, east-2 and west-2. Availability
  and entitlement records passed; effective caller IAM permission is a separate fact.
- IAM simulation for the existing SSO caller and inspection of the runtime candidate-key
  policy were denied. **These inspection limits do not prove missing access.**
  Administrator-console documents were subsequently supplied and reviewed below.

### Administrator-console policy review — November 11, 2026

[admin-policy-evidence.json](../evaluations/ui-shared/admin-policy-evidence.json)
preserves both supplied JSON documents, canonical content hashes, reported roles,
exact required ARNs and explicit evidence limitations. It is a review record, not
an IAM policy deployment input or an AWS API export retrieved by this agent.

| Supplied document | Content coverage | Evidence status |
| --- | --- | --- |
| PowerUserAccess for the existing `AWSReservedSSO_PowerUserAccess_95483085e85e3a9b` role | Unconditional Allow/NotAction excludes `iam:*`, `organizations:*`, `account:*`; `bedrock:InvokeModel` remains allowed on Resource `*`, covering the Nova Lite profile and all three US model ARNs listed in the record. | Administrator-supplied contents and reported association; current attachment/default version and effective access are not independently verified. |
| `enterprise-analytics-dev-q18-candidate-code` for `enterprise-analytics-dev-agent-runtime` | Explicitly allows `s3:GetObject` and `s3:GetObjectVersion` on the exact candidate key. The same object ARN covers versioned reads; the application separately enforces the pinned VersionId. | Administrator-supplied contents and reported association; current attachment and effective access are not independently verified. |

Neither supplied document has a Condition or Deny. Canonical policy hashes are
`7d7c0418e91ec1f2640b715c0875135c7067bc9e4ead04064398e51160c03a0b`
and `82dd281e0e982f27134b0583a84a998886272f713b3a39ccb069183deb8853a7`,
respectively. No policy version/capture timestamp was supplied; none is invented.
The excluded IAM actions explain why this content does not itself grant the failed
inspection calls. Those failures are not evidence of denied Bedrock or S3 reads.

This completes the requested policy-content review. Effective authorization also
depends on actual attachment, boundaries/session policies, organization controls and
applicable resource-policy/explicit denies; these two documents do not enumerate
that state. No billable probe or further IAM inspection was performed for this review.
No specific missing permission is established, and **no new/duplicate grant or IAM
change is proposed**. Accept the stated administrator-reported provenance in the
execution review, preserve original-code access/M3 permissions/query trust, then
repeat fresh target/process/source/publication checks before any approved deployment.

No deployment, upload, IAM change, Athena query, model call or Runtime invocation ran.
Matching source/artifacts are established; **shared live equivalence is pending**.

## Concrete proposal — separate approval required

[review.proposed.json](../evaluations/ui-shared/review.proposed.json) binds
campaign `ui-shared-retail-v1-01`, **20 question attempts**, expiry
**2026-11-11T23:59:00Z**, review SHA
`168abce7775cf9620992c545037643193c41b6756e61179f093c5a8a5653283d`.
New allowance is **0/20, uncreated**; historical campaigns stay unchanged.

One protected AWS Q18 verification + eighteen regular attempts + one protected
original-restoration smoke. Regular attempts are frozen **Q01–Q05, Q13, Q18, Q29,
Q30**, once per backend: all five January regional metrics, North/store filter,
yesterday's March 31 boundary, unsupported grouping and tenant override.
Use existing independent goldens and complete structured plans/results, never prose
or production-derived expectations. The offline paired reporter grades these cases
and the separate Q18 verification and records actual diagnostics.

Reserve/fsync before dispatch, with separate durable SDK receipts/journals.
At most six local Converse attempts/question and one Runtime SDK attempt/question;
SDK retries are disabled. Failed/unknown outcomes stop ordinary dispatch; clarification
still consumes a question even if it uses zero model calls. No automatic reserve reuse,
extra warm-up/demo or retry. Corrupt/missing receipts fail closed. Successful replay
of the same request ID does not dispatch again.

The proposed deployment updates only the existing Runtime to the pinned candidate
and retail configuration. No new resources, bootstrap, IAM changes, dataset publication,
rebuild or upload. Existing per-query 10 MiB Athena and model limits remain; these do
not establish an aggregate dollar cap. Record tokens, latency and query scans.
The regular allocation permits at most 54 direct local Converse SDK attempts
(nine local questions × six); AWS allocation permits ten planned Runtime invocations
(Q18 plus nine paired questions), or eleven including a needed rollback smoke.
Model calls inside Runtime remain separately bounded by its six-iteration agent.
These are separate work ceilings, not additional question allowance.

The proposal is finalized for review with the supplied policy-content evidence,
without claiming effective-access verification. Approval must explicitly cover the
existing candidate/version, successful candidate-retail steady state, failure rollback,
the 20-attempt allocation and the UTC expiry. The review file/pins remain unchanged.
The November 10 AWS observations are historical; fresh execution preflight must pass.

### Commands after permission review and execution approval

Run from the original root in `conda activate enterprise-analytics`. Output paths
must be unused. Prepared copies are already in `artifacts/ui-shared/deployment`;
`assembly-review.json` binds both inventories. Preparation command for a new directory:
`poetry run python -m infrastructure.agentcore.ui_workflow prepare --review evaluations/ui-shared/review.proposed.json --output NEW_DIRECTORY`.

```sh
# Fresh read-only original-v12, publication, identity and process preflight.
poetry run python -m infrastructure.agentcore.ui_workflow preflight \
  --kind original --review evaluations/ui-shared/review.proposed.json \
  --output artifacts/ui-shared/original-preflight.json

# Separate execution approval required:
poetry run python -m infrastructure.agentcore.ui_workflow deploy --execute-approved \
  --review evaluations/ui-shared/review.proposed.json \
  --prepared-dir artifacts/ui-shared/deployment \
  --output artifacts/ui-shared/operations/approved-deploy

# Counted Q18: complete request and 110.25 USD for [2025-03-31, 2025-04-01).
poetry run python -m enterprise_analytics_agent.adapters.ui_shared \
  --purpose verification --invoke-live \
  --review evaluations/ui-shared/review.proposed.json \
  --release-record artifacts/ui-shared/operations/approved-deploy/release-record.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
  --output artifacts/ui-shared/verification.json

# Only after Q18 passes:
poetry run python -m enterprise_analytics_agent.ui --allow-live \
  --shared-review evaluations/ui-shared/review.proposed.json \
  --release-record artifacts/ui-shared/operations/approved-deploy/release-record.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 --port 8501

# After the 18 paired questions, stop UI; grade saved outcomes offline.
poetry run python -m enterprise_analytics_agent.ui.paired_report \
  --review evaluations/ui-shared/review.proposed.json \
  --output artifacts/ui-shared/paired-report.json

# Fresh read-only final candidate proof:
poetry run python -m infrastructure.agentcore.ui_workflow preflight \
  --kind candidate --review evaluations/ui-shared/review.proposed.json \
  --output artifacts/ui-shared/final-preflight.json
```

The bounded deployment controller reconciles exact templates/parameters and complete
artifact/configuration/Runtime/DEFAULT proofs, never READY alone. Logs and task-owned
process evidence are retained; unresolved/overlapping processes stop work. A saved
release record binds the **observed** resulting version, never a guessed v13.
The reviewed candidate differs in code location/version plus trusted retail environment;
foundation, data layer, policies, role access and retained original artifacts stay intact.

Success requires Q18, all eighteen paired outcomes, reporting gates and a fresh final
candidate/retail proof. **Success leaves the shared candidate deployed**; one rollback
slot stays unspent. Do not restore old code and then claim shared alignment.

### Failure, interruption, expiry and original rollback

Stop ordinary dispatch on failure/denial/drift. After a candidate deployment attempt,
restore original when controller/process guards establish it is safe. Failed deployment
automatically attempts original restoration; evaluation failure requires commands below.
Stop UI first. On interruption inspect journals before resuming cleanup; do not overlap
deployments or discard unresolved state.

```sh
poetry run python -m infrastructure.agentcore.ui_workflow restore --execute-approved \
  --review evaluations/ui-shared/review.proposed.json \
  --prepared-dir artifacts/ui-shared/deployment \
  --output artifacts/ui-shared/operations/approved-rollback

poetry run python -m enterprise_analytics_agent.adapters.ui_shared \
  --purpose rollback_smoke --invoke-live \
  --review evaluations/ui-shared/review.proposed.json \
  --release-record artifacts/ui-shared/operations/approved-rollback/rollback-record.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
  --output artifacts/ui-shared/rollback-smoke.json
```

Verify original pins/configuration/templates/policies and actual resulting READY
versions; protected smoke must return North **28.50 USD**, South **13.00 USD**.
Shared billable modes then stay disabled. Cleanup is independent of candidate source/
canonical availability and can proceed after expiry. Expiry blocks all new billable
dispatch, including smoke, but cannot cancel in-flight work. Allow enough time for
cleanup; if expiry prevents smoke, record the gap and seek a separate decision.
Never extend/reset an active ledger or infer additional permission.

## Historical handoff and verification

The downloaded patch was forward/reverse checked, applied once after
`git apply --check`, and initially reversed cleanly. Its isolated **1,161 passing
tests** are supplied historical evidence, not this checkout's result. It corrected
endpoint `liveVersion` and supplied the source-audit handoff. The original endpoint
dispatch regression failed with KeyError; the corrected code passed. Existing local
work was backed up before application. Actual checks are in [progress](progress.md).

Official references:
[Converse](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html),
[GetAgentRuntimeEndpoint](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/get_agent_runtime_endpoint.html),
[IAM simulation](https://docs.aws.amazon.com/boto3/latest/reference/services/iam/client/simulate_principal_policy.html),
[Botocore configuration](https://docs.aws.amazon.com/botocore/latest/reference/config.html),
[S3 prefix inventories](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/list_objects_v2.html),
[Glue table schemas and locations](https://docs.aws.amazon.com/boto3/latest/reference/services/glue/client/get_table.html).

Policy review references checked November 11, 2026:
[IAM Allow with NotAction](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_notaction.html),
[IAM effective-policy evaluation](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html),
[Bedrock profile and regional-model prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html),
[S3 operation permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html).
