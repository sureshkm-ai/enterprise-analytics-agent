# Selectable models and readable streaming

## Later request failures and client repair

The owner subsequently reported **24/40** attempts with only Qwen enabled.
The four-model results below are the earlier acceptance checkpoint. Follow
[the client repair](workbench-request-repair.md) to inspect the retained requests
and restart with the exact operator binding, preserving the existing release
and ledger. The repair corrects invocation timeouts and failure classification;
it has not been live-validated on the owner's Mac. Six failed-acceptance models
remain disabled. Do not rebuild the deployed ZIP or reset a campaign.

## Historical acceptance checkpoint at 20/40

Open **http://127.0.0.1:8501/?mode=live** and refresh an older page. **Nova Lite,
DeepSeek V3.2, Qwen3 235B and Mistral Large 3** are enabled in **Local agent** and
**AWS AgentCore** modes. Select a model, enter a question and click the run button.
The composer clears; readable provider words stream before the validated final
result. Offline playground stays separately labeled.

All four passed both authored AWS cases. Actual browser checks passed Local Q18
for all four and AWS Nova Q18: exact **110.25 USD for March 31, 2025**, full date
boundaries and independent goldens. Usage is **20/40**, with **18 ordinary questions**
until **November 15, 2026, 5:59 p.m. CST**. Cleanup and reserve remain unused. This
is partial acceptance; six failing models are explicitly unavailable.

Original server launch at that checkpoint (use the repair runbook above for the current client):

```sh
conda activate enterprise-analytics
poetry run python -m enterprise_analytics_agent.ui --port 8501 --allow-live \
  --streaming-review evaluations/bedrock-streaming/review.workbench.proposed.json \
  --streaming-releases artifacts/bedrock-streaming/workbench-fix/operations-approved-01/releases.actual.json \
  --streaming-approval artifacts/bedrock-streaming/workbench-fix/approval.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1
```

The server is already running; do not start a second process on port 8501. Restarting
cannot reset the allowance or extend expiry. Actual ZIP is `f2755c33…`, S3 VersionId
`xnQiGsnGRkgFV3ktJ2DfhUbOClx9gVEn`; all ten Runtime/DEFAULT bindings independently
verified READY **v4** at **2026-11-13T15:59:41Z**. Legacy v15 and M3 data/trust remain
unchanged. See [actual outcome](../evaluations/bedrock-streaming/workbench.outcome.json).

Anthropic/OpenAI returned complete AWS account-model-unavailability errors, not
an established missing IAM grant. Gemma failed iteration bounds and Llama failed
the complete all-five case. [Diagnostics](../evaluations/bedrock-streaming/workbench.model-diagnostics.json)
preserve actual reasons; no failing model was retried or silently substituted.

## Implementation and preparation history

This change follows `5f5fa06389c5b9cc8302153ef25169c88215d249` on
`feat/bedrock-streaming-activation` (PR #13). It implements one selected model per
question, shared local/AWS presentation, and independent model acceptance. It
does not establish live access to every model or reopen an old allowance.

## What was wrong

- The accepted Nova v15 binding returns progress and a final JSON response. It
  cannot provide provider-word streaming merely by changing the browser.
- The streaming implementation copied the technical semantic answer, including
  metric identifiers and interval notation, into the visible UI.
- A single failed model stopped the entire acceptance campaign and caused all
  ten candidate deployments to be restored. No other models could be tried.
- Explicit model bindings inherited the unconfigured default slot's error in
  some backends. The UI could say "not connected" while a target was configured.
- A status refresh could erase a request error before the user could inspect it.

## Implemented behavior

The existing model selector routes an opaque model key to its fixed server-owned
configuration. The browser cannot supply a model ARN, tenant, credentials or
scope. Local Bedrock uses DuckDB; AgentCore uses Athena. Both use the same
`StreamingAnalyticsAgent` and `agent/presentation.py`.

Readable answers are rendered from validated semantic results, with exact Decimal
strings, business metric names, inclusive human date labels and grouped tables.
For example, Q18 displays **Net revenue: 110.25 USD for March 31, 2025**. The
underlying response retains `[2025-03-31, 2025-04-01)` and its original exact
contract. Null ratios and empty results are explicit. Browser code performs no
metric arithmetic. Data and execution details are available in a disclosure;
downloaded JSON retains the original semantic response.

The presentation call streams real provider characters matching that readable
answer. A Runtime prelude carries `display_answer`; the receiving adapter
independently recomputes it before publishing words. A changed number, date or
final presentation fails validation. The final word stays held until terminal
events and usage validate. Existing raw-text streaming envelopes remain readable.
The browser uses a small DOM-based Markdown renderer, never `innerHTML`, and
handles fragmented UTF-8, partial text and final consistency checks. Heartbeats
remain progress, not generated text. No automatic retry or model fallback exists.

## Independent model policy

Historical `bedrock-model-stream-v1` and continuation reviews preserve their
original fail-stop behavior and hashes. Their closed ledgers remain closed.

A **new, explicitly approved** `bedrock-model-workbench-v1` review provides:

- One shared cap of at most 40 question attempts, including one protected cleanup
  attempt and one unused reserve. `ordinary_limit = maximum_attempts - 2`.
- Completed failures quarantine the selected model in both local and AWS modes;
  another configured model can still be selected. Failed attempts remain spent.
- Incomplete accounting, expiry, exhausted allowance or completed cleanup still
  blocks the entire session. A disconnect never cancels durable accounting.
- Per-model Q18 and all-five-regional acceptance, with immutable claims and
  separate reports under `acceptance/<model-key>.json`.
- An optional `--model-testing` UI mode for user-driven testing before full
  acceptance. Choices explicitly say **Testing**; it is not an acceptance claim.
  This flag rejects historical review schemas and requires the exact new approval,
  source, artifact, data and deployed release bindings.

`bedrock-workbench-preparation-v1` uses the existing deployment controller with a
freshly bound restored baseline, rather than the historical hardcoded v1/3-used
continuation. Every target still gets exact preflight, update and release proof.
If at least one model passes both authored cases, independently accepted models
remain deployed and the outcome says `partially_accepted` when appropriate. Failed
models remain disabled. If none passes, or deployment/accounting cannot be
reconciled, the existing restoration and protected-smoke procedure applies.

## Run and validate

Offline UI (no AWS access required):

```bash
poetry run python -m enterprise_analytics_agent.ui --port 8501
```

Open `http://127.0.0.1:8501/`. The offline playground uses the deterministic
planner; its model selector is intentionally disabled. For example:

- What was net revenue in January 2025 by region?
- Show order count for January 2025 by region and channel.
- Show gross sales, net revenue, order count, average order value, and return rate
  for January 2025 by region.

Build a separate streaming candidate with locked ARM64 dependencies, leaving all
frozen artifacts untouched:

```bash
poetry run python -m infrastructure.agentcore.package \
  --config infrastructure/agentcore/runtime.streaming.nova-lite.json \
  --entrypoint infrastructure/agentcore/streaming_entry.py \
  --output artifacts/bedrock-streaming/workbench-fix/agent.zip \
  --wheel-dir artifacts/bedrock-streaming/workbench-fix/wheels
```

The output path must be new. A reproduced archive can use `--offline` with the
verified dependency wheels. Bind the returned ZIP digest/size, current
`source_digest`, canonical manifest and synthesized template digests in a new
workbench review. Use the existing ten-model CDK configuration, changing only
the candidate artifact binding and retaining the original restoration key.
Keep `ArtifactVersionId` unbound during offline synthesis; bind the actual S3
version returned by the approved upload.

In the original checkout, obtain fresh read-only evidence through `analytics-dev`
for the ten restored streaming targets, original code version, stack IDs, complete
templates, original legacy v15 target and process guard. The expected last recorded
streaming version is v3, but fresh observations determine the baseline. Pin these
files in a **new** `bedrock-workbench-preparation-v1` preparation. Approval must
bind both its hash and the new review hash. Never edit or reuse the historical
completion preparation or its approval to authorize this candidate.

The existing operator then accepts the new preparation through the same commands:

```bash
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan PATH_TO_NEW_PREPARATION verify-offline
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan PATH_TO_NEW_PREPARATION preflight --read-only-aws --output NEW_PREFLIGHT_DIR
# After approval of the concrete review/preparation:
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan PATH_TO_NEW_PREPARATION execute --execute-approved \
  --approval PATH_TO_NEW_APPROVAL --output NEW_OPERATION_DIR
```

After candidate releases are verified, launch the UI with their actual binding:

```bash
poetry run python -m enterprise_analytics_agent.ui --allow-live \
  --streaming-review PATH_TO_NEW_REVIEW \
  --streaming-releases NEW_OPERATION_DIR/releases.actual.json \
  --streaming-approval PATH_TO_NEW_APPROVAL
```

Add `--model-testing` only when the approved new scope includes interactive testing
of unaccepted models. Failed models remain blocked even with that flag. To run
acceptance for a selected model in a separately prepared workbench session, the
existing `adapters.model_stream_cli evaluate` supports repeated `--model KEY`;
each model can be evaluated only once in that session.

## Historical pre-execution evidence and remaining boundary

The implementation has offline regression coverage for the real semantic loop,
Runtime stream validation, actual shipped JavaScript, fragmented UTF-8 delivery,
model selection, separate acceptance, failure isolation and restoration controls.
The prior turn's browser review used clearly labeled fixture backends and made
no AWS/model calls. That review is not live model acceptance. Current validation
results are recorded in [progress](progress.md).

The implementation-only clone originally lacked the authenticated session and
ignored checkpoints; that was historical handoff context. The original checkout
has now verified `analytics-dev`, current deployments and retained assets through
fresh read-only calls. All ten streaming stacks verified UPDATE_COMPLETE and
Runtime/DEFAULT READY v3; legacy Nova remains READY v15. The current port-8501
process uses the old accepted-Nova launcher and correctly disables it because
106b173 changes its source pin. It is not the new workbench.

The [concrete deployment/acceptance proposal](ui-model-workbench-deployment-proposal.md)
was fully prepared: reproducible new ARM64 ZIP, exact source/configuration/review,
two matching syntheses, original restoration assembly, fresh baseline and formal
preflight, and a separate untouched 40-slot campaign. Its actual commands replace
the illustrative placeholders above. See the
[readiness summary](../evaluations/bedrock-streaming/workbench.readiness.json).
At that preparation checkpoint no upload, deployment or billable invocation had
occurred. The owner subsequently approved its exact review/preparation, expiry,
attempt allocation and restoration; actual results are recorded above. The old
accepted-Nova binding and historical failed reviews cannot authorize it.

The later full Sonnet message establishes account/model unavailability; no missing
IAM grant is supported. The recorded live streaming/browser acceptance applies to
the four enabled models only, not failing choices or unexecuted cases.
