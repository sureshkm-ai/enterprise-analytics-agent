# Workbench model expansion

The owner reports that these seven models work in the AWS console. They now have
distinct workbench bindings using the exact Bedrock identifiers below. DeepSeek
V3.2 was already supported and is included once. Nova Lite, Qwen3 235B A22B 2507
and Mistral Large 3 remain in the new ten-model selection. Historical failed
Claude 5.5, GPT, Gemma 4 and Llama targets are not renamed or treated as accepted.

| Model | Bedrock invocation ID | Planning / presentation |
| --- | --- | --- |
| [Claude Sonnet 4.6](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html) | `us.anthropic.claude-sonnet-4-6` | Converse / ConverseStream |
| [Claude Opus 4.6](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-4-6.html) | `us.anthropic.claude-opus-4-6-v1` | Converse / ConverseStream |
| [Gemma 3 12B IT](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-google-gemma-3-12b-it.html) | `google.gemma-3-12b-it` | Converse / ConverseStream |
| [NVIDIA Nemotron 3 Super 120B A12B](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-nvidia-nemotron-super-3-120b.html) | `nvidia.nemotron-super-3-120b` | Runtime Chat Completions / SSE |
| [Qwen3 VL 235B A22B](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-qwen-qwen3-vl-235b-a22b.html) | `qwen.qwen3-vl-235b-a22b` | Converse / ConverseStream |
| [Kimi K3](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-moonshot-ai-kimi-k3.html) | `us.moonshotai.kimi-k3` | Runtime Chat Completions / SSE |
| [DeepSeek V3.2](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-deepseek-deepseek-v3-2.html) | `deepseek.v3.2` | Converse / ConverseStream |

The console's `v1` label is not an instruction to append `-v1` or `:0` to IDs.
Qwen's Runtime ID differs from its Mantle ID, which ends in `-instruct`.
The application continues to accept text questions, including for vision models.

## Implementation

Local DuckDB and AWS Athena runners use the same catalog, governed agent, tool
validation and readable presentation. Kimi and Nemotron use the AWS-signed
`https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1/chat/completions`
route with refreshed AWS credentials, sequential tools and `reasoning_effort=none`.
There is no provider API key, new AWS profile or automatic invocation retry.
The bridge retains terminal usage checks, fragmented SSE decoding, exact model
identity checks, private reasoning suppression and resource cleanup. HTTP denials
retain redacted AWS code/message/request ID through the existing diagnostic sink.

Kimi's [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-moonshot-ai-kimi-k3.html)
documents Converse multi-turn failures when replaying earlier reasoning blocks,
and recommends Chat Completions. Reasoning defaults to max effort there, so this
adapter explicitly disables it in both phases. The Claude 4.6 choices use default
thinking-off behavior. The shared 5-planning-plus-1-presentation call bound,
12,000-token ceiling and semantic authorization remain unchanged. See AWS's
[Chat Completions authentication](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html).

The new review opts into the existing accepted-model request-recovery policy.
This optional field is omitted from historical reviews, preserving their hashes
and fail-stop behavior. Unknown errors and failed acceptance still pause a model;
transient recovery never sends an automatic question or resets accounting.

## Prepare the new release offline

The [selection](../evaluations/bedrock-streaming/models.account-available.json) is
configuration, not live acceptance or approval. The old workbench allowance
expired on **November 15, 2026 at 23:59 UTC**. Do not edit its expiry, approval,
source hashes, acceptance records or ledger. The six new aliases need six new
fixed-model roles/Runtimes; the four retained choices need the matching new code
version for local/remote source equality. Keep the six historical failed stacks
and the separate legacy Runtime unchanged.

Offline verification built the ARM64 ZIP twice with identical SHA-256
`746faf9e7ac37f0c07ed9bd2012fc1fe456c28606f791f924e4f7af40b6e051e`
(39,332,180 bytes), verified its complete package source against this checkout,
and synthesized all ten proposed targets. This is an unuploaded candidate; no
S3 VersionId or live acceptance is implied. Rebuild from the same locked source
in the original checkout before binding a new review.

From the updated original checkout, build a separate candidate:

```sh
poetry run python -m infrastructure.agentcore.package \
  --config infrastructure/agentcore/runtime.streaming.nova-lite.json \
  --entrypoint infrastructure/agentcore/streaming_entry.py \
  --output artifacts/bedrock-streaming/account-models/candidate/agent.zip \
  --wheel-dir artifacts/bedrock-streaming/account-models/wheels
```

The embedded Nova configuration is a packaging default; every synthesized Runtime
has its own exact `ANALYTICS_RUNTIME_CONFIG` with the selected model ID.
The packaging command rejects an existing candidate path. Preserve earlier builds;
choose a fresh path if preparing a changed source tree.

```sh
poetry run python -m infrastructure.agentcore.prepare_workbench_models \
  --artifact artifacts/bedrock-streaming/account-models/candidate/agent.zip \
  --output artifacts/bedrock-streaming/account-models/proposal \
  --campaign-id bedrock-stream-account-models-01 \
  --expires-at 2026-11-24T23:59:00Z
```

That expiry is a proposal, not an extension of any earlier allowance. Use a future
reviewed window if executing later. This command verifies the candidate's source
members, entry point, manifest and lock binding, then creates ten offline CDK
templates, a deployment config, a source/artifact/template-bound review, additive
permission proposals and a readiness checklist. It makes no AWS call and creates
no approval, actual release record, invocation claim or ledger. It refuses old
campaign IDs and existing output directories.

## Activation in the original checkout

1. Use only `analytics-dev` in the existing account and Oregon region. Collect
   fresh retained-template/Runtime/DEFAULT/release, query-trust and canonical
   publication evidence. Confirm each US profile's concrete destination ARNs
   with `GetInferenceProfile`; the proposal uses the three regions documented
   for Oregon. Console success is useful access evidence, but does not verify
   each new workload role or the application's semantic acceptance.
2. Compare `permissions.additions.proposed.json` with effective administrator
   evidence. Its CloudFormation additions cover the six new exact role names,
   their `PassRole`, runtime/identity lifecycle and tagging, plus the exact new
   code key. Existing shared-directory/create-time grants remain necessary.
   Append only missing permissions; preserve M3 and every existing grant. The
   synthesized workload policies include both Bedrock invocation actions, exact
   profile/base ARNs and the existing query role. Merge the six new query-trust
   principals after the roles exist, preserving developer and older principals.
   Never replace the whole query trust document with the additions file.
3. Bind the fresh baseline/restoration evidence and review the actual creation
   and update diff before approval. **Do not pass this proposal to the historical
   `streaming_completion execute` command:** that recovery controller requires
   the original ten existing stacks and original artifact version; this scope
   contains six new stacks. Use the synthesized CDK application for the approved
   six creations and four updates, with the existing deployment controller for
   exact completion reconciliation. Retain before/after evidence and owned
   process journals. Do not delete or replace any old failed-model stack.
4. After explicit approval of that concrete deployment and a fresh allowance,
   upload the verified ZIP once, bind its real S3 VersionId, deploy and verify
   exact code/settings, Runtime/DEFAULT, inbound policies and log retention.
   Write the actual `StreamingReleases` record with every real ARN/version and
   template/configuration digest. Never invent a VersionId or reuse old releases.
5. Run the existing independent Q18 and all-five-regional acceptance for each of
   the ten choices. Proposed allocation: 20 AWS acceptance questions, 10 Local
   Q18 browser checks, 8 ordinary user questions, 1 protected cleanup and 1
   unavailable reserve = 40 maximum. Every attempt, including a failure, counts.
   Use only the separately approved allocation; enable only passing models.
   For a systemic deployment failure, restore the four updated targets to their
   fresh captured baseline; preserve evidence for any created targets and perform
   only the explicitly approved cleanup. Partial model failures remain isolated.
6. Launch with the new review, actual releases and approval. Do not supply the
   old `--streaming-operator-repair` overlay: this release changes agent adapters
   and requires its own source/archive binding. Refresh the browser and select
   **Local agent** or **AWS AgentCore**, then the accepted model.

The existing UI and evaluator consume this new review schema without a separate
frontend model ID override. Live activation remains pending until the
original-checkout evidence and approval above are complete.
