# Progress

Updated: 2026-11-05 (America/Chicago).

## Current milestone and status

**Milestone 1 — local semantic execution: acceptance passed.** Its implementation, semantic-review fixes, documentation, and session workflow form the initial local milestone checkpoint. Completion is recorded by the successful local commit containing this handoff; verify its hash with `git log -1 --oneline` and its state with `git status --short`.

At the start of this session, `main` had no commits and all 27 project files were untracked. The earlier implementation was verified but had not been committed. No later milestone has been started or authorized. Keep commits local; no push has been requested.

## Completed work

- Poetry src-layout package and lockfile on Python 3.12.16 in Conda `enterprise-analytics` (Poetry 2.3.1).
- Versioned Pydantic v2 contracts, four semantic tools, governed metric catalog, and a DuckDB snapshot adapter with separate trusted tenant/region authorization.
- Fixed-seed six-table retail Parquet generator and `analytics-demo` querying net revenue by region.
- Independent accounting, authorization, contract-boundary, reproducibility, and CLI tests. Required refund, cancellation, duplicate-event, empty-result, and date-boundary scenarios pass.
- All six requested documents and credential/generated-artifact ignore rules. Existing `.DS_Store` files and unrelated files are preserved and excluded from the checkpoint.
- Root `AGENTS.md` now records session-start reconciliation, ordered milestone scope, acceptance checks, concise handoffs, authorized local commits, failure handling, and post-commit reporting. Existing instructions are preserved.

## Important decisions

- Net revenue uses completed/shipped merchandise sales, line-total discounts once, USD cents at rest and exact Decimal dollars in responses; tax/shipping are excluded.
- Only approved refunds count. They reduce the original order period, including approvals after the query end; no as-of cutoff. Time ranges are UTC business dates with inclusive start and exclusive end.
- Exact business-record replays collapse; conflicting records with the same tenant-scoped key are rejected. Refunds aggregate per item before joins, and payment events never join revenue.
- The focused review found no arithmetic, date-boundary, or authorization bypass. It corrected execution metadata exposed by descriptions: public payloads and JSON schemas now use business descriptions; expressions and source/join mappings stay internal.
- Unreleased v1 description schemas were corrected before the first commit. Query contracts and metric definition 1.0.0 arithmetic are unchanged; published incompatible contracts require a new version.
- Keep the milestone local. AWS, Bedrock, AgentCore, Athena, and Cube integrations require a later explicit request and current official SDK documentation.

Full architecture and accounting assumptions remain in `docs/architecture.md` and `docs/metric-definitions.md`; future scope remains in `docs/implementation-plan.md`.

## Latest acceptance verification

Commands actually run in this session:

| Command | Actual result |
| --- | --- |
| `git status --short` and `git ls-files --others --exclude-standard` | Initial state: 27 project files untracked; no staged changes or unrelated source work. |
| `git log -5 --oneline` | Initial state: no commits on `main`; Git reported that the branch had no commits. |
| `python --version` and `poetry env info` | Python 3.12.16; active `enterprise-analytics` Conda environment. |
| `poetry run pytest` | **68 passed in 7.06s**. |
| `poetry run ruff check .` | Passed: all checks passed. |
| `poetry run ruff format --check .` | Passed: 23 files already formatted. |
| `poetry run mypy src tests` | Passed: no issues in 17 source files. |
| `poetry check --lock` | Passed: All set. |
| `poetry run analytics-demo --data-dir data/retail` | Exit 0; East $1158.41, North $1023.15, South $643.88, West $1119.27. |
| `git diff --cached --check` | Passed: no staged whitespace errors. |
| Staged diff statistics, file list, and scoped diffs | Reviewed 27 milestone files; no unrelated artifacts or credentials staged. |

No required checks were skipped. Independent read-only acceptance review found no concrete blockers or unrelated artifacts among the 27 candidate files. Generated Parquet, credentials, caches, and OS files are ignored.

Earlier verification: Poetry lock/install succeeded after an approved PyPI retry; four new metadata-boundary regressions failed before the fix and pass afterward. Eight added accounting regressions protect existing behavior. Literal examples: two distinct $1.50 refunds reduce $32.50 to $29.50 even with a replay; a $9 December order refunded $2 in January stays $7 in December; adjacent windows yield $7, $32.50, and $7, with a $46.50 combined total.

## Blockers and known limitations

No acceptance blockers. Initial staging failed because the sandbox denied writing `.git/index.lock`; the approved retry succeeded. Completion remains contingent on the successful local checkpoint. Record any commit failure here and do not advance until resolved.

Only `net_revenue`, USD, and `region`/`channel` dimensions are supported. Ingestion requires six application-controlled schemas and an in-memory snapshot. Over-refunds may produce negative net revenue. There is no complete accounting reconciliation, as-of query, FX, streaming, production authentication/policy service, or deployed agent. The CLI supplies fixed local authorization. No AWS calls have been made.

## Exact next task

After this checkpoint, stop: no further milestone is authorized. On the next session, read `docs/implementation-plan.md` and this file, inspect `git status` and recent commits, and reconcile them with this handoff. If the user requests another milestone, establish its scope and acceptance criteria before implementation; consult current official SDK documentation before any external integration. Do not infer permission to deploy, call AWS, start a future milestone, or push commits.
