# Progress

Updated: 2026-11-05 (America/Chicago).

## Current milestone and repository state

**Milestone 2 — complete local semantics and CI: acceptance passed.** Completion is recorded by the successful local milestone commit containing this handoff. Verify with `git log -2 --oneline` and `git status --short`. Branch: `feat/milestone-2-local-semantics-ci`, based on completed milestone 1 commit `64cbea4`. Keep this branch local; the user will push it.

Baseline inspection read AGENTS, README, and all four docs. `main` was clean at `64cbea4`. Before changes, all five required checks passed, including 68 tests in 7.07s. Python and Poetry both used `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16, Poetry 2.3.1). A second explicit environment assertion confirmed the same existing Conda environment before final tests. No local environment replacement or dependency upgrade was needed; `pyproject.toml` and `poetry.lock` are unchanged.

## Completed work

- Documented all five metric definitions before calculations; preserved net revenue definition 1.0.0 and its eligibility/time semantics.
- Added all five metrics through separate v2 contracts: exact currency/count/nullable-ratio values, appropriate grains, units, precision, and public business metadata. V1 contracts remain byte-unchanged; nine frozen schema fingerprints and literal net revenue JSON protect compatibility.
- Added optional deterministic physical return events, statuses, quantities, tenant-scoped references, duplicate handling, and missing-return-data errors. Six-table snapshots remain usable for the other metrics.
- Preserved all original six logical datasets for the same seed, verified with twelve frozen milestone 1 fingerprints (six tables, two seeds). Return generation uses a separate random stream and guarantees financial/physical return distinctions at the order level.
- Added item/order aggregation without join fanout; distinct received-return order flags; exact aggregate ratios rounded only at the end. The CLI preserves default v1 net revenue and adds metric/API selection.
- Retained the original accounting, contract, and authorization coverage and added independent multi-metric, return, precision, compatibility, filtering, and CLI tests.
- Added push/PR GitHub Actions CI with SHA-pinned official actions, Python 3.12, Poetry 2.3.1, read-only permissions, locked dependency sync, and the five required checks. README, all four docs, and root instructions reflect milestone 2 and the new roadmap.

## Decisions and reasons

- V1 remains net-revenue-only. V2 supports currency, count, and ratio results without changing published v1 schemas. Currency and ratio values are decimal strings; counts are integers. Nonmonetary v2 results have `currency: null`.
- Completed/shipped USD orders with at least one valid item qualify. Invalid snapshot records fail validation. Tenant/region scope comes only from trusted application context; purchase-time region/channel control grouping and authorization.
- Refunds and physical returns are independent facts. Approved refunds reduce net revenue; received physical returns count an order once, even with partial returns or multiple returned items. Both use the original order date and loaded snapshot with no as-of cutoff.
- Average order value uses aggregate net revenue / aggregate order count; return rate uses returned-order count / eligible order count. Integer rational arithmetic applies final ROUND_HALF_UP at 2/6 places independently of Decimal context. Zero denominators are null. Payment events never join metric aggregates.
- The generated-table assertion was extended from six to seven; legacy schemas and fixture helpers stay six-table-compatible. Golden dataset fingerprints are compatibility checks, never expected answers for metrics; metric tests use authored data and literal arithmetic.
- CI configuration follows current official action releases and Poetry docs, linked in README/architecture. Local `poetry sync --help` confirmed the pinned Poetry supports the flags; sync was not executed against the existing Conda environment.

## Actual verification commands and results

| Command | Final result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **212 passed in 23.71s**. |
| `poetry run ruff check .` | Passed: all checks passed. |
| `poetry run ruff format --check .` | Passed: 28 files already formatted. |
| `poetry run mypy src tests` | Passed: no issues in 22 source files. |
| `poetry sync --help` | Confirmed support for `--with dev --no-interaction`. |
| `git diff --check` and `git diff --cached --check` | Passed. Reviewed the 19-file milestone diff; v1 contracts, project dependencies, and lockfile are unchanged. |

All five CLI commands below exited 0 using the fixed default period/seed. They were executed sequentially against `data/retail`; these are observed demo outputs, not test oracles:

`poetry run analytics-demo --data-dir data/retail --metric <metric>` was run once for each row:

| Metric | East | North | South | West |
| --- | ---: | ---: | ---: | ---: |
| gross_sales (USD, v2) | 1294.75 | 1150.50 | 733.50 | 1233.50 |
| net_revenue (USD, v1) | 1158.41 | 1023.15 | 643.88 | 1119.27 |
| order_count (v2) | 16 | 18 | 9 | 17 |
| average_order_value (USD, v2) | 72.40 | 56.84 | 71.54 | 65.84 |
| return_rate (fraction, v2) | 0.000000 | 0.166667 | 0.111111 | 0.117647 |

Independent worked fixture: gross $53.00, net $42.50, three orders, AOV $14.17, return rate 0.333333; the regional ratios are not averaged. Tests also cover half-up ties ($0.005 -> $0.01 and 1/128 -> 0.007813), caller Decimal precision 2, missing versus empty return sources, received returns without refunds, refunds without returns, multiple items/events, exact/conflicting replays, empty queries, boundaries, and tenant/region isolation for every metric.

Focused verification was run while implementing; initial formatting/lint issues were fixed. Independent read-only source/CI review found no concrete blockers. No required local checks were skipped.

## Blockers and limitations

No acceptance blockers. Initial feature-branch creation was denied by the sandbox's read-only Git metadata restriction; the approved retry succeeded. If commit creation fails, record it here and do not advance until resolved.

Hosted GitHub Actions has not run: the branch remains local, and pushing belongs to the user. No AWS credentials, calls, deployment, Athena adapter, or Bedrock/AgentCore integration were introduced. Data remains an application-controlled in-memory snapshot; there is no production policy service, FX, as-of history, streaming, or complete financial/cumulative physical-return ledger. Over-refunds can produce negative net revenue/AOV. Present optional return files are validated even when another metric is queried.

## Exact next task

Stop after the milestone 2 local commit. The user may push `feat/milestone-2-local-semantics-ci` and inspect its first CI run. In a future session, read plan/progress and inspect Git before resuming. Milestone 3 (AWS data layer/Athena adapter with parity tests) and milestone 4 (Bedrock/AgentCore) require a new explicit request; neither has been started. Check current official SDK documentation before any external integration, and do not push on the user's behalf without authorization.
