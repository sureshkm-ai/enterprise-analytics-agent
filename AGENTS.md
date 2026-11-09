# Repository instructions

## Scope and architecture

- Keep milestones 1 and 2 local: no AWS calls, credentials, or external services.
- Milestone 3 permits implementation, offline synthesis/tests, and read-only verification using an explicitly selected AWS profile. Finish the concrete deployment plan before asking for approval; bootstrap, resource creation, source publication, and live parity require that approval. Do not mark it complete until live parity passes.
- Milestone 4 permits local implementation/verification, read-only AWS configuration checks, and local commits. Finish `docs/agentcore-deployment-plan.md` and reviewed packaging/infrastructure before requesting approval for resources, IAM changes, or billable model/runtime evaluations. Keep milestone 4 open until deployed-agent acceptance passes. Keep commits local.
- Milestone 5 permits operator-side implementation, offline verification, local commits, and explicitly authorized read-only canonical downloads/checkpoint inspection. Deployment, IAM changes, uploads, publication, Athena execution and model/Runtime calls need separate approval. Preserve M4's 28/40 ledger; use the separate persistent M5 counter for every later approved call, including failures and the protected restoration smoke. Freeze retail expectations only from verified canonical publication bytes using the independent oracle. Keep M5 open until live evaluation and corrected-base restoration pass.
- The Q18 repair uses the explicitly selected `q18-repair-v1` campaign and its separately bound ledger; the original M5 campaign stays closed at 38/40. Preserve original restoration ZIP/key/version/template pins. Candidate execution requires the reviewed new ZIP/template and a real post-upload version record, never a guessed version or global replacement of restoration constants. Follow the repair proposal and confirm candidate-key read access before requesting live approval; offline preparation authorizes no AWS operations.
- Q18 continuation uses only the reviewed `q18-continuation-v1` selector, explicit original-v8 checkpoint and separate ledger. Preserve the closed repair ledger at 1/40 byte-for-byte; validate its hash read-only and cap continuation at 39 calls, aggregate 40 including the prior call. The final continuation call is protected for original restoration. The full 39-call proposal consumes the previously controlled reserve and needs explicit approval before execution. Keep the durable attempt claim and whole-operator lease; never reset/reopen a campaign or bypass an unresolved deployment process journal. Reconcile CDK with exact CloudFormation template/parameters and full Runtime/DEFAULT artifact/configuration proof; READY alone is insufficient. Controller corrections are operator-side and do not authorize rebuilding/uploading the frozen candidate.
- The approved Q18 continuation ended closed at1/39, aggregate repair 2/40, after a post-controller connection timeout; original restoration/smoke passed on v10. Preserve that ledger/claim and the historical v8 review. Only 38 calls remain, fewer than the prescribed39-call sequence. Do not reopen/reset or treat unused quota as permission for another attempt; offline diagnosis and a new reviewed scope/budget decision come first.
- The agent consumes backend-independent, versioned semantic contracts.
- AWS-specific and Cube-specific logic belongs only in adapters. Do not expose SQL or provider SDK types in the semantic interface.
- The semantic tools are `discover_metrics`, `describe_metric`, `query_metric`, and `discover_dimensions`.
- Metric definitions own calculations, allowed dimensions, relationships, filters, units, and time semantics. Update `docs/metric-definitions.md` before changing a calculation.
- Authorization comes from trusted application context passed separately to adapters, never from model-supplied identity arguments. Deny access outside that context.
- Agent requests contain only the question. The development AgentCore runtime uses IAM-authenticated approved callers and a fixed server-configured tenant/region scope. Payloads, headers, sessions, history, and model text cannot define authorization. Deployed code uses workload credentials, never a local profile or SSO credentials.
- Bedrock uses a bounded Converse loop exposing only the four semantic operations through validated v2 requests. Render numeric answers from validated semantic results, preserving exact values and versions; never substitute model-generated calculations. Clarify ambiguous or unsupported intent rather than silently guessing.
- Keep default tests and ordinary CI free of AWS calls. Billable deployed-agent tests require explicit `--run-agent-live --agent-config=...` and prior approval; missing configuration must fail instead of silently skipping acceptance. AgentCore Gateway, Memory, Browser, Code Interpreter, Evaluations service, Cube, and UI work remain outside milestone 4.
- Validate SDK usage against current official documentation when implementing external integrations. Do not add speculative Bedrock, AgentCore, Athena, or Cube integrations.

## Development

- Use Python 3.12, Poetry and its committed lockfile, Pydantic v2, DuckDB, and Parquet.
- Keep package code under `src/enterprise_analytics_agent` and tests under `tests`.
- The retail CLI/evaluator is operator-side; its target metadata never supplies runtime authorization. SDK creation and AWS checkpoint/provenance reads belong in adapters. Default replay/oracle/tests must not create AWS clients. `--run-retail-live --retail-config=...` and CLI `--invoke-live` are explicit execution gates, not substitutes for approval.
- Preserve existing work; do not overwrite unrelated changes or commit credentials or generated data.
- Store money as integer cents in data and use `Decimal` in semantic responses. Never use binary floating point for money.
- Bind SQL values; only interpolate identifiers selected from the governed metric definition.
- Use fixed seeds and fixed date ranges for synthetic data. Test fixtures must be small and independently calculated, not generated by the production generator.
- Verify with `poetry check --lock`, `poetry run pytest`, `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests`.
- Record commands actually run, results, assumptions, and remaining work in `docs/progress.md`.

## Session and milestone workflow

1. At the beginning of each session, read `docs/implementation-plan.md` and `docs/progress.md`. Inspect `git status` and recent commits to verify the recorded state against the repository. If `docs/progress.md` does not exist, create it using the repository's actual state.
2. Work through the requested milestones in order. Complete and commit each milestone before starting the next. Continue only through milestones included in the user's request.
3. Before marking a milestone complete, verify its acceptance criteria and run the project's required tests, linting, and type checks. Fix failures caused by the changes. Record any checks that could not run and why.
4. Update `docs/progress.md` before each milestone commit and before ending a work session. Keep it concise and include:
   - Current milestone and status.
   - Completed work and remaining work.
   - Important decisions and their reasons.
   - Verification commands and actual results.
   - Blockers or known limitations.
   - The exact next task and enough context to resume it.
5. After a milestone passes its required checks, review the diff and create a descriptive local Git commit containing its implementation, tests, and updated documentation. The user has authorized these local commits without asking again. Stage only files belonging to the milestone and preserve unrelated changes.
6. If a milestone is blocked or a commit fails, record the issue accurately. Do not claim completion or advance to the next milestone until it is resolved.
7. After committing, report the commit hash, what was completed, verification results, and the next task. Keep commits local unless the user requests a push.
