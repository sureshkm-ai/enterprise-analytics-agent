# Bedrock model selection and provider word streaming

The user **approved execution of this development deployment and live evaluation**
on November 11, 2026, after PR #11 merged at `01aabc1`. The scope is separate from
completed Milestones 1–5 and every historical campaign. Approval is recorded in
`artifacts/bedrock-streaming/approval.json` and remains valid for the unchanged plan.
The first read-only preflight verified the retained v15/canonical checkpoint and
routing. A November 12 read-only follow-up confirms all three model agreements
are AVAILABLE and the administrator report verifies both attached policy parts.
Deployment remains stopped on the report's shared-directory TagResource
implicitDeny. The supplement confirms the exact request and current M4 policy:
its directory grant requires the old Project value. A separate, exact-directory
TagResource correction now has separate user approval, recorded independently
of the unchanged deployment review. Administrator application/readback and an
allowed post-change simulation remain pending. See [administrator steps](bedrock-streaming-administrator-steps.md) and
the [actual preflight record](../evaluations/bedrock-streaming/activation-preflight-2026-11-11.json). The existing
Nova candidate/retail Runtime and DEFAULT remain the retained **v15** checkpoint;
the existing interactive allowance and its ledger are unchanged. A new model is
listed in the UI catalog as a documented choice, not as an enabled or accepted
backend.

## Behavior and model scope

Local Bedrock execution and AWS execution share `BedrockAnalyticsAgent`, the four
validated semantic operations, metric definitions and v2 contracts. Local
execution uses verified canonical DuckDB data; each new AWS Runtime uses Athena.
The deterministic playground and saved reports remain AWS-free. A UI selection
is an opaque server binding; the deployed payload still contains only a question.
Each deployed model has its own fixed configuration, role, Runtime and DEFAULT
endpoint. Model selection cannot change tenant/region authorization.

The planner uses the existing bounded tool loop, with at most **five planning
calls**, followed by **one tool-free presentation call**. Native models use
Converse for planning and ConverseStream for presentation. This also supports
Meta's restriction against streaming tool use. Google Gemma uses AWS-signed
Bedrock Mantle `/openai/v1` chat requests, sequential tool calls and its streaming
response; it does not use a direct Google service or a Gemini API key.

The presentation must reproduce the canonical answer rendered from validated
metric results. The UI publishes actual provider text only while it matches that
answer's exact prefix and reaches a complete word boundary. It retains an
unfinished numeric word and the last word until the protocol, stop condition and
usage metadata validate. A changed amount/date, extra text, truncated stream or
malformed event fails the request. Private reasoning is retained only where the
provider requires it for the next planning turn and is never displayed. This is
provider-backed word streaming after semantic execution; progress messages while
the tools run are labeled separately. There is no timer that animates a saved
answer and no display of unvalidated model calculations.

The first release proposes exactly these ten new fixed-model runtimes:

| Model key | Bedrock model/inference profile | Transport and relevant restriction |
| --- | --- | --- |
| `nova-lite` | `us.amazon.nova-lite-v1:0` | Native Converse; accepted model family, new streaming release |
| `claude-sonnet-5-5` | `us.anthropic.claude-sonnet-5-5` | Native US profile; omit temperature and preserve private reasoning |
| `claude-opus-5-5` | `us.anthropic.claude-opus-5-5` | Native US profile; omit temperature and preserve private reasoning |
| `gpt-6-astra` | `us.openai.gpt-6-astra` | Native US profile; omit unsupported temperature |
| `gpt-6-1-sol` | `us.openai.gpt-6.1-sol` | Native US profile; omit unsupported temperature |
| `gemma-4-31b` | `google.gemma-4-31b` | Bedrock Mantle; one tool at a time; Gemma rather than Gemini |
| `llama-4-maverick` | `us.meta.llama4-maverick-17b-instruct-v1:0` | Native US profile; nonstreaming tools, tool-free text stream |
| `deepseek-v3-2` | `deepseek.v3.2` | Native Converse and tool-free ConverseStream |
| `qwen3-235b` | `qwen.qwen3-235b-a22b-2507-v1:0` | Native Converse and tool-free ConverseStream |
| `mistral-large-3` | `mistral.mistral-large-3-675b-instruct` | Native Converse and tool-free ConverseStream |

The catalog also describes `gpt-oss-120b`, but that eleventh option is outside
this deployment and budget. No provider is called universally best. The authored
evaluations establish suitability for these analytics questions; quotas,
subscription/licensing, effective access and regional availability still require
fresh evidence for every deployed model. US inference-profile routing is part of
the requested approval and must match the exact destination model ARNs in the
reviewed configuration.

## Target, resources and immutable evidence

Only profile **`analytics-dev`**, account **`453711491609`**, region **`us-west-2`**
may be used. No profile creation or default-profile fallback is permitted.

The new CDK app creates ten `enterprise-analytics-stream-<model-key>` stacks,
ten same-named execution roles and ten `enterprise_analytics_stream_<model_key>`
Runtimes with service-created DEFAULT endpoints/workload identities. Each Runtime
gets both inbound resource policies restricted to the reviewed existing SSO
caller role. The approved log groups have seven-day retention. Runtime sessions
idle out after 300 seconds and have a 900-second maximum lifetime; the agent
request deadline is 90 seconds and Athena query deadline is 60 seconds.

Reuse the existing code bucket, retained source/results storage, Glue database,
Athena workgroup and query role. Source data is the verified `retail-v1` snapshot,
tenant `retail_demo`, regions North/South, reference date `2025-04-01`. The new
runtime code uses workload credentials and refreshable query-role assumptions.
There is no bootstrap, dataset publication, current Runtime update, rebuild of an
accepted historical artifact, or M3 permission replacement.

The preparation record must pin these items before execution approval:

| Evidence | Reviewed location / required value |
| --- | --- |
| New ARM64 ZIP and embedded manifest | `artifacts/bedrock-streaming/candidate/agent.zip`; record actual SHA-256 and size |
| New source/dependency fingerprint | `evaluations/bedrock-streaming/review.proposed.json`; include the new streaming modules and existing shared closure |
| New exact S3 key | `releases/<new ZIP SHA-256>/agent.zip` in the existing agent-code bucket |
| Real S3 VersionId | Unbound before upload; record the actual conditional-upload response once approved |
| Ten Runtime configurations/templates | `infrastructure/cdk/streaming.proposed.json` and `artifacts/bedrock-streaming/cdk.reviewed.out`; review SHA-256 per template |
| Review, expiry and campaign binding | `evaluations/bedrock-streaming/review.proposed.json`; record its final SHA-256 and commit |
| Additive deployment policy | `infrastructure/cdk/streaming-deployment-policy.proposed.json`; pin its final hash after replacing the new ZIP key |
| Canonical retail manifest | `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797` |

The existing accepted candidate remains SHA-256
`398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1`, S3 VersionId
`V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu`. Its historical source, configuration,
assembly, goldens, ledgers and release records remain unchanged. The recorded v15
state is historical until a fresh read verifies it. A newly built streaming ZIP
must have its own key and actual version; it cannot inherit this old VersionId.

## Verified local preparation pins

Prepared offline on November 11, 2026 (America/Chicago; UTC November 12).
The committed [preparation record](../evaluations/bedrock-streaming/preparation.json)
contains the complete assembly inventory and per-template canonical/file hashes;
[build manifest](../evaluations/bedrock-streaming/build-manifest.json) records all
13 checksum-locked Python 3.12 Linux ARM64 dependencies. All **76** application
source/assets files and the new entry point were compared with the actual ZIP.
A second synthesis in a separate directory produced **ten byte-identical templates**.
No AWS operation, upload or new question dispatch was performed.

| Pin | Value |
| --- | --- |
| Review semantic SHA-256 | `cf222d7e870e0d033a5b65d4f74876a581b83f237f651c0eaa6033745b86c76d` |
| New source SHA-256 | `c2311efc915339f0e7b7d7d86da660d037fb84be700332e45006299b3b70b687` |
| New ZIP SHA-256 | `c136a3931e2af31d6453c54910ddc9e839ef03e69a6f2ddebb35b3eb7cfdc306` |
| ZIP bytes | `39298651` |
| Deployment config file SHA-256 | `ab4019e79cf0e7b57978869873550ed6dfcc26b14c7f6f84cdf9a024675f2258` |
| Additive policy file SHA-256 | `9be307f2bf73232c6146a7cfda8eb90e31d4952af2eb0de5ce8eb79e51a8723f` |
| Real uploaded VersionId | **Not created**; remains null before separately approved upload |
| Campaign | `bedrock-stream-models-v1-01`, proposed **0/40**, no ledger/claim created |

The five-planning-call cap also works for sequential-tool Gemma: after the fifth
successful query, the wrapper may finish only if every exact required metric,
period, grouping/filter request and result is complete, without duplicates or tool
errors. An exhausted partial/time/token/error result is never promoted. The shared
legacy agent and its existing six-iteration behavior remain unchanged.

## IAM changes requiring review

An administrator must attach the approved permissions **additively** to
`arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`.
The aggregate audit policy has 8,147 compact characters, above IAM's 6,144 managed
policy limit. Its exact statements are therefore packaged into two policies:
[roles/code](../infrastructure/cdk/streaming-deployment-policy.roles.proposed.json)
(2,294) and [AgentCore](../infrastructure/cdk/streaming-deployment-policy.agentcore.proposed.json)
(5,891), with [hash/equivalence evidence](../evaluations/bedrock-streaming/policy-packaging.json).
Attach both as described in the administrator guide. No permission was changed.
Together they add lifecycle/PassRole access only for the ten exact new roles, scoped
Runtime/endpoint/resource-policy actions, automatic workload-identity permissions
in the new namespace and read access to the exact new ZIP key. Runtime creation
and automatic DEFAULT creation/tagging use account/region/Project conditions.
It contains no bucket lifecycle, old role replacement, M3 grants, new bootstrap
or service-linked-role creation. Existing M3/M4 policies stay attached.

Each new workload role gets exact new-code read permission, scoped log writes,
`sts:AssumeRole` for the existing query executor and its own inference actions.
Native inference grants `bedrock:InvokeModel` and
`bedrock:InvokeModelWithResponseStream` on the exact model/profile/destination
ARNs in the reviewed config. Mantle grants `bedrock-mantle:CreateInference` on
`arn:aws:bedrock-mantle:us-west-2:453711491609:project/default`, conditioned on
`bedrock-mantle:Model = google.gemma-4-31b` and the selected region. This is
project authorization, not a foundation-model ARN substituted for Mantle.

The existing query role needs ten additive trusted principals. The CDK templates
output `QueryRoleTrustAdditionProposalOnly`; they deliberately do not modify
that role. The same ten exact principals are consolidated in
[one additive statement](../infrastructure/cdk/streaming-query-trust-additions.proposed.json)
to reduce the final trust-document size. An administrator must merge that statement into the current trust
document, preserving the existing developer SSO and legacy Runtime principals.
Capture before/after evidence and the exact role list; never replace trust with
only the new principals. Prepare/review that delta before deployment, then apply
it after the new roles exist and before any model evaluation; IAM cannot trust
nonexistent role principals. Attachments/effective access require evidence
separate from policy-content review.

The supplied PowerUserAccess contents cover Bedrock invocation and Mantle
actions through Allow/NotAction; the supplied candidate-code policy covers the
**old** accepted key. They do not prove current attachments, SCP/boundary/session
effects, access to the new key by new roles, or subscriptions. Do not infer a
missing grant from denied IAM inspection or add duplicate speculative grants.

Historical M4 creation needed permission to tag the shared default workload
identity directory. The old grant is conditioned on the old Project value.
The proposed additive policy intentionally contains **no new directory-tagging
grant**. Administrator/read-only evidence must establish the existing directory
state and whether creation requires that shared-resource operation for the new
project. Stop before execution while this remains unresolved; capture a complete
parent/nested denial if one still occurs. Any correction needs an evidence-backed
review and approval, not automatic IAM broadening. Likewise verify the existing
Mantle default project and applicable model access before deployment/evaluation.

## Offline preparation commands

Use the existing activated Conda environment and confirm Python 3.12/Poetry before
these commands. The package command writes a separate new ZIP and refuses to
overwrite an existing output when using the new entry point.

```bash
poetry run python -m infrastructure.agentcore.package \
  --config infrastructure/agentcore/runtime.streaming.nova-lite.json \
  --entrypoint infrastructure/agentcore/streaming_entry.py \
  --offline --wheel-dir artifacts/agentcore/wheels \
  --output artifacts/bedrock-streaming/candidate/agent.zip
poetry run python -m infrastructure.cdk.streaming_app \
  --config infrastructure/cdk/streaming.proposed.json \
  --outdir artifacts/bedrock-streaming/cdk.reviewed.out \
  --allow-unbound-artifact
poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
  --review evaluations/bedrock-streaming/review.proposed.json verify-offline
poetry check --lock
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests
git diff --check
```

Run separate reproduction/synthesis verification directories when checking
reproducibility; preserve the reviewed output. The unbound preview templates
have a required `ArtifactVersionId` parameter **without a default**. They may be
reviewed offline, but deployment must bind the actual post-upload version. No
invented version is a deployable pin. Record actual offline results in
[progress](progress.md); earlier hosted results do not cover this release.

## Proposed live budget and gates

Propose one separate campaign bound to the final review and expiring at
**2026-11-15T23:59:00Z**. Expiry closes billable dispatch even if quota remains;
it does not restore spent allowance or authorize execution. Do not start a
deployment/evaluation unless its bounded deployment deadlines, remaining authored
question deadlines and at least 45 additional minutes for diagnosis/cleanup all
fit before expiry. Do not rely on unused quota as cleanup time.

| Purpose | Maximum question attempts |
| --- | ---: |
| Mandatory AWS authored acceptance, two per model | 20 |
| User-owned interactive questions across local/AWS after acceptance | 18 |
| Protected retained-v15 verification/cleanup smoke | 1 |
| Controlled reserve, **unapproved and unusable without further approval** | 1 |
| Outer campaign ceiling | 40 |

The implementation limits ordinary reservations to 38 and separately protects
cleanup. Every attempt, including failures and disconnects, is reserved durably
before SDK dispatch and counted once. Every actual model/Runtime SDK request also
has a pre-dispatch receipt and terminal outcome. Billable SDK automatic retries
are disabled. Do not retry an unsuccessful question, reset a journal, replace a
claim or spend the protected slot on ordinary usage. There is no extra warm-up:
each model's Q18 check is its counted warm-up.

Each question permits at most six model calls and 12,000 combined reported
input/output tokens, with conservative input-byte guards before calls. The outer
40-attempt ceiling therefore bounds model SDK calls at **240** and combined
tokens at **480,000**; the unapproved reserve is not spendable just because it is
inside that ceiling. The presentation call consumes the same token/time budget.
Failed transports may leave provider token usage unavailable; report that as
unknown/incomplete, retain attempted-call receipts and do not report it as zero.

For every model, acceptance requires both of these **AWS** questions to pass
complete structured request/result judgment against existing independent goldens:

1. Q18: `Show net_revenue for yesterday.` Reference date `2025-04-01` must yield
   `net_revenue = 110.25 USD` for **[2025-03-31, 2025-04-01)** with the complete
   expected request, scope and versions.
2. `Show gross_sales, net_revenue, order_count, average_order_value and return_rate for January 2025 by region.`
   Require all five full requests and North/South results, exact monetary/ratio
   precision, units/null behavior, dates and versions from frozen Q01–Q05 values.

Both resource policies, exact template/parameters, code bucket/key/version,
configuration hash, authorization, DEFAULT target version, READY status and
seven-day retention must match before tests. READY alone is not acceptance.
All twenty checks must pass before enabling this release in the UI. Private
reasoning must remain absent and actual provider-word delivery must complete
without a changed canonical number. Record latency, model usage, model/Runtime
versions, tool calls and Athena diagnostics. Evaluate structured values rather
than exact model prose. A failed/incomplete attempt stops ordinary dispatch.

## Later approved deployment and evaluation

The following execution commands are **approved**, subject to every documented
preflight gate. No repeated approval is required for the unchanged scope.
Use a new evidence directory; retain stdout/stderr, process journal, CloudFormation
events and exact read-only proofs. Resolve all administrator prerequisites first.

1. Verify `aws sts get-caller-identity --profile analytics-dev --region us-west-2`.
   Freshly verify the untouched retained v15 Runtime, DEFAULT, policies, artifact,
   retail configuration and retention. Check task-owned process/lease guards,
   canonical S3 objects and Glue bindings, source/ZIP hashes, reviewed templates,
   unchanged existing role trust plus the reviewed additive trust delta,
   model/profile routing/access and Mantle default project.
   An unavailable required check is a blocker; do not replace it with READY.
2. After explicit approval, upload the reviewed ZIP **once**, conditionally:

   ```bash
   STREAM_ZIP_SHA256=c136a3931e2af31d6453c54910ddc9e839ef03e69a6f2ddebb35b3eb7cfdc306
   STREAM_ZIP_SHA256_BASE64=wTajkx4q8x1kU8VJEN3J6DnvA+aaby3euzWz63z9wwY=
   AWS_MAX_ATTEMPTS=1 aws s3api put-object --profile analytics-dev --region us-west-2 \
     --bucket enterprise-analytics-dev-453711491609-us-west-2-agent-code \
     --key "releases/$STREAM_ZIP_SHA256/agent.zip" \
     --body artifacts/bedrock-streaming/candidate/agent.zip \
     --checksum-algorithm SHA256 --checksum-sha256 "$STREAM_ZIP_SHA256_BASE64" \
     --expected-bucket-owner 453711491609 --if-none-match '*' \
     > artifacts/bedrock-streaming/upload-response.json
   ```

   `$STREAM_ZIP_SHA256` must be the pinned review hash. Read the response's real
   VersionId into `$STREAM_VERSION_ID`; verify that exact object/hash/size before
   deploying. A conditional conflict stops execution; do not overwrite a key.
   Explicit SHA-256 upload metadata is required because target verification
   requires the exact returned `ChecksumSHA256`, rather than an ETag/default CRC.
3. Deploy each of the ten reviewed stacks **sequentially**, with the same actual
   version. First verify each reviewed assembly's CloudFormation execution-role
   field resolves to the existing execution role named above:

   ```bash
   cdk deploy --app artifacts/bedrock-streaming/cdk.reviewed.out \
     "enterprise-analytics-stream-$STREAM_MODEL_KEY" \
     --profile analytics-dev --require-approval never \
     --parameters "ArtifactVersionId=$STREAM_VERSION_ID" \
     --outputs-file "artifacts/bedrock-streaming/outputs.$STREAM_MODEL_KEY.json"
   ```

   Do not substitute `--role-arn` with the CloudFormation service-role ARN:
   that CLI option changes the role the caller assumes when using CloudFormation.
   The reviewed assembly supplies the service execution role. Use only the ten
   reviewed model keys. Preserve logs and reconcile completion
   against the exact expected CloudFormation template/parameters plus full
   Runtime/DEFAULT artifact/configuration/policy proof. If the local CDK process
   stalls after AWS succeeds, verify that state within a bounded deadline before
   cleaning up only the task-owned process. Never overlap deployments, accept a
   stale READY version, rerun a mutation just because CDK did not exit, or proceed
   through rollback/unresolved/unavailable verification. On an AWS failure stop
   repeated deployments, retain full CloudTrail parent/nested error messages and
   compare principal/action/resource/conditions to reviewed policy evidence.
4. Read each actual `RuntimeLogGroupName` output. If that exact **new** group is
   absent, create it with `aws logs create-log-group`; then set
   `aws logs put-retention-policy --retention-in-days 7`. Both commands use the
   selected profile/region and the exact output name. Creation of these ten log
   groups is included in the requested scope and avoids an uncounted invocation
   solely to initialize logs. Do not change legacy log groups or account-wide
   log delivery. Read back seven-day retention before release binding.
   Once the ten roles exist, have the administrator apply only the reviewed
   query-role trust additions and retain before/after effective-policy evidence.
   Recheck the preserved developer/legacy principals before any invocation.
5. Bind actual verified releases and run all twenty checks once:

   ```bash
   poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
     --review evaluations/bedrock-streaming/review.proposed.json \
     bind-releases --read-only-aws \
     --upload-response artifacts/bedrock-streaming/upload-response.json \
     --output artifacts/bedrock-streaming/releases.actual.json
   poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
     --review evaluations/bedrock-streaming/review.proposed.json \
     --releases artifacts/bedrock-streaming/releases.actual.json \
     --approval artifacts/bedrock-streaming/approval.json \
     evaluate --invoke-live --output artifacts/bedrock-streaming/acceptance
   ```

   The approval record must bind the exact final review SHA, expiry and maximum
   attempts. Global CLI arguments precede the subcommand. Do not create a false
   approval record, bind a guessed endpoint/version or interpret configuration as
   user approval. Acceptance reports and the persistent ledger are prerequisites
   to enabling user questions.
6. After every gate passes, launch the single-user loopback UI:

   ```bash
   poetry run python -m enterprise_analytics_agent.ui --port 8501 \
     --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
     --streaming-review evaluations/bedrock-streaming/review.proposed.json \
     --streaming-releases artifacts/bedrock-streaming/releases.actual.json \
     --streaming-approval artifacts/bedrock-streaming/approval.json --allow-live
   ```

   Local Bedrock mode is explicitly billable before submission. A model is
   enabled only after this campaign's AWS checks pass. Do not mix the new review
   with historical shared-release arguments. Startup/catalog selection dispatches
   no question. Browser disconnection does not retry the question or release its
   execution lock before backend accounting completes.

## Failure, cleanup and cost

On a failed deployment, verification, stream or judgment, stop ordinary dispatch
and disable the new bindings. Keep all logs, receipts, pending process evidence
and attempted-call diagnostics. The legacy candidate-retail v15 was never
updated by this deployment; verify its exact original checkpoint rather than
blindly redeploying an old assembly. The separately protected new-campaign smoke
can confirm that retained release, using its own receipt rather than an old
ledger. This operator path deliberately does not depend on availability of the
new ZIP/source/canonical downloads or new release bindings:

```bash
poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
  --review evaluations/bedrock-streaming/review.proposed.json \
  --approval artifacts/bedrock-streaming/approval.json \
  cleanup --invoke-live --output artifacts/bedrock-streaming/cleanup.json
```

The cleanup result must independently match Q18 **110.25 USD** on the retained
retail scope; it is not the old parity North/South smoke. Stop if the legacy
checkpoint drifted; there is no permission to overwrite an unrelated change.
Use that protected call only within the approved expiry and never as a retry.
Delete only the explicitly approved ten new stacks/log groups during cleanup,
remove only their added query-role trust statements after confirming no active
use, and preserve retained code objects/data/results and every historical role.
Administrator cleanup of the additive deployment policy is a separate exact
attachment removal, never replacement of the existing execution policies. No
automatic cleanup command may delete the legacy Runtime, foundation or data layer.

The question/token limits are usage bounds, **not a fixed dollar cap**. Estimate
model cost per model as input tokens × its input rate plus output/reasoning tokens
× its applicable output rate; include any provider-specific billing rules.
AgentCore adds active CPU and memory usage, Athena adds billed bytes with its
minimum/rounding and existing scan limits, and S3/CloudWatch add storage, requests,
ingestion and retained logs. Verify current [Bedrock model prices](https://aws.amazon.com/bedrock/pricing/),
[AgentCore prices](https://aws.amazon.com/bedrock/agentcore/pricing/),
[Athena prices](https://aws.amazon.com/athena/pricing/),
[S3 prices](https://aws.amazon.com/s3/pricing/) and
[CloudWatch prices](https://aws.amazon.com/cloudwatch/pricing/) before approval.
There is no promise that ten expensive-model sessions cost the same as Nova.

## Official references and remaining gates

The [checked model catalog](../src/enterprise_analytics_agent/adapters/bedrock_model_catalog.py)
links each exact official model card. API/protocol and permission references used:

- [ConverseStream SDK events](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html),
  [ConverseStream API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html),
  and [chat-completions routing](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html).
- [Mantle project resources and model condition keys](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-mantle.html)
  and [Bedrock projects/default project](https://docs.aws.amazon.com/bedrock/latest/userguide/projects.html).
- [AgentCore HTTP/SSE contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html),
  [Runtime invocation SDK](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html),
  and [AgentCore IAM resource/action reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html).
- [CDK deploy parameters](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-deploy.html)
  and [CDK global role/profile options](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd.html).
- [Conditional PutObject and explicit SHA-256 checksum options](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html).

Offline checks establish implementation readiness only. Execution approval is now
recorded; retain the frozen checksums and real-version binding procedure. Resolve
the remaining directory correction's administrator application/readback and
allowed simulation documented in the administrator guide, then repeat fresh
preflight and continue
the already approved ten-runtime scope. The controlled reserve remains unusable.
No live acceptance, new permission, upload, deployment or production-readiness
claim is recorded here.
