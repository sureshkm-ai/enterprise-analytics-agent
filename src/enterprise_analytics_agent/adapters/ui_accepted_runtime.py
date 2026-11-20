"""Approved AWS-only transport for frozen Nova v15, using its existing ledger.

No source equivalence with the current local agent is asserted. Construction and
status are offline; every actual question freshly proves AWS and publication
bindings before the unchanged shared ledger reserves its invocation.
"""

import ast
import hashlib
import importlib.util
import json
import time
import tomllib
import zipfile
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from uuid import uuid4

import boto3

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.adapters.retail_provenance import verify_local
from enterprise_analytics_agent.adapters.ui_live import runtime_lease
from enterprise_analytics_agent.adapters.ui_release import (
    LOCK_SHA256,
    ReleaseRecord,
    make_record,
    validate_record,
    verify_publication,
    verify_release,
)
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.retail_evaluation.cases import (
    load_goldens,
    load_suite,
    verify_frozen_inputs,
)
from enterprise_analytics_agent.retail_evaluation.client import validate_target_response
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.reporting import _redact
from enterprise_analytics_agent.ui.accepted_runtime import (
    AcceptedRuntimeApproval,
    AcceptedRuntimeReview,
    checked_path,
    verify_approval,
)
from enterprise_analytics_agent.ui.models import (
    AskRequest,
    UiError,
    UiResult,
    unreported_diagnostics,
)
from enterprise_analytics_agent.ui.shared import SdkAttemptRecorder, SharedLedger, SharedReview

MAX_MODULE_BYTES = 1024 * 1024


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operator_source_digest(root: Path) -> str:
    inventory = {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted((root / "src").rglob("*"))
        if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
    }
    if any((root / name).resolve() != root / name for name in inventory):
        raise UiError("The approved operator source must not contain aliased files.")
    return hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()


def archive_source_inventory(archive: zipfile.ZipFile) -> dict[str, str]:
    """Audit the frozen static core closure inside ZIP bytes without importing code."""
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise UiError("The accepted archive contains duplicate members.")
    available = set(names)
    pending = deque(
        (name, True)
        for name in (
            "enterprise_analytics_agent.hosting.server",
            "enterprise_analytics_agent.adapters.bedrock_agent",
            "enterprise_analytics_agent.adapters.duckdb",
        )
    )
    visited: set[str] = set()
    inventory: dict[str, str] = {}
    while pending:
        name, required = pending.popleft()
        if name in visited or not (
            name == "enterprise_analytics_agent" or name.startswith("enterprise_analytics_agent.")
        ):
            continue
        base = name.replace(".", "/")
        path = next((p for p in (base + ".py", base + "/__init__.py") if p in available), None)
        if path is None:
            if required:
                raise UiError("A required accepted archive core module is missing.")
            continue
        visited.add(name)
        if archive.getinfo(path).file_size > MAX_MODULE_BYTES:
            raise UiError("An accepted archive module exceeds its size limit.")
        content = archive.read(path)
        inventory[path] = hashlib.sha256(content).hexdigest()
        parts = name.split(".")
        pending.extend((".".join(parts[:index]), True) for index in range(1, len(parts)))
        package = name if path.endswith("/__init__.py") else name.rpartition(".")[0]
        for node in ast.walk(ast.parse(content, filename=path)):
            if isinstance(node, ast.Import):
                pending.extend((item.name, True) for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported = node.module or ""
                if node.level:
                    imported = importlib.util.resolve_name("." * node.level + imported, package)
                pending.append((imported, True))
                pending.extend((f"{imported}.{item.name}", False) for item in node.names)
    entry = "runtime_entry.py"
    if entry not in available or archive.getinfo(entry).file_size > MAX_MODULE_BYTES:
        raise UiError("The accepted archive entrypoint is missing or oversized.")
    inventory[entry] = hashlib.sha256(archive.read(entry)).hexdigest()
    return dict(sorted(inventory.items()))


def verify_archive_inputs(root: Path, review: AcceptedRuntimeReview) -> dict[str, object]:
    """Verify accepted frozen bytes/dependencies/data, independently of current core."""
    archive_path = checked_path(root, review.archive_path)
    if (
        archive_path.stat().st_size != review.archive_bytes
        or digest(archive_path) != review.archive_sha256
    ):
        raise UiError("The accepted frozen archive checksum or size changed.")
    with zipfile.ZipFile(archive_path) as archive:
        inventory = archive_source_inventory(archive)
    source_hash = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    if len(inventory) != 25 or source_hash != review.archive_source_sha256:
        raise UiError("The accepted archive's 25-file core closure changed.")
    manifest_path = checked_path(
        root, archive_path.with_suffix(".manifest.json").relative_to(root).as_posix()
    )
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != review.archive_manifest_sha256:
        raise UiError("The accepted archive build manifest changed.")
    manifest = json.loads(manifest_bytes)
    committed = json.loads(
        checked_path(root, "evaluations/retail-v1/q18-build-manifest.json").read_bytes()
    )
    if manifest != committed or manifest["zip_sha256"] != review.archive_sha256:
        raise UiError("The accepted archive manifest differs from the frozen build.")
    lock = checked_path(root, "poetry.lock")
    if digest(lock) != LOCK_SHA256:
        raise UiError("The operator lockfile differs from the accepted runtime dependencies.")
    locked = tomllib.loads(lock.read_text())["package"]
    dependencies = manifest["dependencies"]
    if len(dependencies) != 13:
        raise UiError("The accepted dependency inventory changed.")
    for item in dependencies:
        matching = [
            p for p in locked if p["name"] == item["name"] and p["version"] == item["version"]
        ]
        if (
            len(matching) != 1
            or metadata.version(item["name"]) != item["version"]
            or "sha256:" + item["sha256"] not in {f["hash"] for f in matching[0]["files"]}
        ):
            raise UiError("An accepted runtime dependency/version/checksum changed.")
    canonical = checked_path(root, review.canonical_directory)
    verify_local(canonical)
    old = SharedReview.model_validate_json(
        checked_path(root, review.shared_review_path).read_bytes()
    )
    if digest(canonical / "manifest.json") != old.canonical_manifest_sha256:
        raise UiError("The accepted canonical data manifest changed.")
    provenance = json.loads(
        checked_path(root, "evaluations/retail-v1/oracle-provenance.json").read_bytes()
    )
    local = json.loads((canonical / "provenance.json").read_bytes())
    if local["manifest"] != provenance["manifest"] or local["objects"] != provenance["objects"]:
        raise UiError("The accepted canonical publication provenance changed.")
    questions = checked_path(root, "evaluations/retail-v1/questions.json")
    expected = checked_path(root, "evaluations/retail-v1/expected-results.json")
    suite = load_suite(questions)
    goldens = load_goldens(expected, suite)
    verify_frozen_inputs(
        questions,
        expected,
        checked_path(root, "evaluations/retail-v1/oracle-provenance.json"),
        goldens,
    )
    return {"archive_source_sha256": source_hash, "archive_core_files": len(inventory)}


def load_bindings(root: Path, review: AcceptedRuntimeReview) -> tuple[SharedReview, ReleaseRecord]:
    """Load immutable historical inputs; this function grants no execution approval."""
    shared_path = checked_path(root, review.shared_review_path)
    release_path = checked_path(root, review.release_record_path)
    if (
        digest(shared_path) != review.shared_review_file_sha256
        or digest(release_path) != review.release_record_file_sha256
    ):
        raise UiError("The original shared review or v15 release record changed.")
    shared = SharedReview.model_validate_json(shared_path.read_bytes())
    release = ReleaseRecord.model_validate_json(release_path.read_bytes())
    if (
        shared.sha256 != review.shared_review_sha256
        or shared.campaign_id != "ui-shared-retail-v1-02"
        or review.expires_at > shared.expires_at
        or release.runtime_version != "15"
    ):
        raise UiError("The AWS-only binding cannot change the old campaign, expiry or v15.")
    validate_record(shared, release)
    return shared, release


def require_ready_budget(state: dict[str, object]) -> None:
    purposes = state["purposes"]
    if (
        state["blocked"]
        or not isinstance(purposes, dict)
        or purposes["verification"] != 1
        or purposes["rollback_smoke"] != 0
        or not isinstance(state["regular_remaining"], int)
        or state["regular_remaining"] <= 0
        or not isinstance(state["used"], int)
        or state["used"] < 2
    ):
        raise UiError(
            "The existing interactive-02 question allowance is not ready; do not reset it."
        )


def verify_offline(
    root: Path,
    review: AcceptedRuntimeReview,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Preparation only: preserve the current ledger and create no SDK session/claim."""
    root = root.resolve()
    review = AcceptedRuntimeReview.model_validate(review.model_dump())
    shared, release = load_bindings(root, review)
    if now() >= review.expires_at:
        raise UiError("The proposed binding has expired; no execution is permitted.")
    if operator_source_digest(root) != review.operator_source_sha256:
        raise UiError("The approved AWS-only UI operator source changed; keep live disabled.")
    local = verify_archive_inputs(root, review)
    budget = SharedLedger(root, shared, now=now).summary()
    require_ready_budget(budget)
    return {
        "passed": True,
        "aws_calls": 0,
        "review_sha256": review.sha256,
        "shared_review_sha256": shared.sha256,
        "release": release.model_dump(mode="json"),
        "local": local,
        "budget": budget,
        "execution_approval": "separate approval required; preparation does not authorize calls",
    }


def verify_read_only(
    root: Path,
    review: AcceptedRuntimeReview,
    output: Path,
    *,
    read_only_aws: bool = False,
) -> dict[str, object]:
    """Fresh exact release/publication inspection, with no Runtime invocation."""
    if not read_only_aws:
        raise UiError("Fresh preflight requires explicit read-only AWS selection.")
    root = root.resolve()
    output = output.absolute()
    if output.resolve() != output or not output.is_relative_to(root) or output.exists():
        raise UiError("Use a new unaliased preflight output in the checkout.")
    offline = verify_offline(root, review)
    shared, release = load_bindings(root, review)
    pool = ReadPool(None, output.with_suffix(".reads.jsonl"))
    try:
        with runtime_lease(root):
            pool.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
            checkpoint = verify_release(
                shared,
                kind="candidate",
                session=pool.view(time.monotonic() + 180, "ui-accepted-readonly-release"),
            )
            observed = make_record(shared, checkpoint, kind="candidate")
            if observed != release.model_copy(update={"observed_at": observed.observed_at}):
                raise UiError("Fresh release proof differs from the accepted v15 binding.")
            publication = verify_publication(
                shared,
                pool.view(time.monotonic() + 180, "ui-accepted-readonly-publication"),
                root=root,
            )
            # Keep this proof coherent with the operator files and allowance at
            # the end of the read-only window, without reserving any question.
            offline = verify_offline(root, review)
            result = {
                "passed": True,
                "read_only_aws": True,
                "observed_at": datetime.now(UTC).isoformat(),
                "offline": offline,
                "checkpoint": checkpoint,
                "publication": publication,
                "runtime_invocations": 0,
            }
            encoded = json.dumps(_redact(result), indent=2) + "\n"
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x") as stream:
                stream.write(encoded)
            return result
    except BaseException as exc:
        try:
            pool.record(
                {
                    "event": "ui-accepted-readonly-failed",
                    **error_record(exc, "ui-accepted-readonly"),
                }
            )
        except Exception:
            pass
        raise


class AcceptedRuntimeQuestions:
    """AWS-only release binding with the unchanged interactive-02 review/ledger."""

    def __init__(
        self,
        root: Path,
        review: AcceptedRuntimeReview,
        approval: AcceptedRuntimeApproval,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.root = root.resolve()
        self.review = AcceptedRuntimeReview.model_validate(review.model_dump())
        if not isinstance(approval, AcceptedRuntimeApproval):
            raise UiError("A separate explicit AWS-only runtime approval is required.")
        self.approval = AcceptedRuntimeApproval.model_validate(approval.model_dump())
        self.now = now
        self.shared_review, self.release = self._bindings()
        self.ledger = SharedLedger(self.root, self.shared_review, now=now)
        self._local_proof()

    def _bindings(self) -> tuple[SharedReview, ReleaseRecord]:
        verify_approval(self.review, self.approval, self.now())
        return load_bindings(self.root, self.review)

    def _local_proof(self) -> dict[str, object]:
        shared, release = self._bindings()
        if shared != self.shared_review or release != self.release:
            raise UiError("The accepted release binding changed after startup.")
        if operator_source_digest(self.root) != self.review.operator_source_sha256:
            raise UiError("The approved AWS-only UI operator source changed; keep live disabled.")
        return verify_archive_inputs(self.root, self.review)

    def _ready_summary(self) -> dict[str, object]:
        state = self.ledger.summary()
        require_ready_budget(state)
        return state

    def public_state(self, mode: str) -> dict[str, object]:
        if mode != "live":
            return {"enabled": False, "error": "This accepted-runtime binding supports AWS only."}
        error = ""
        try:
            self._local_proof()
            self._ready_summary()
        except (ValueError, OSError, UiError, zipfile.BadZipFile, SyntaxError) as exc:
            error = str(exc)
        return {
            "enabled": not error,
            "error": error,
            "dataset": "retail-v1",
            "reference_date": "2025-04-01",
            "tenant": "retail_demo",
            "regions": ["North", "South"],
            "runtime_version": "15",
            "description": "AWS AgentCore · accepted Nova Lite retail v15 · AWS only",
            "cost_notice": (
                "BILLABLE: AgentCore + Bedrock + Athena; existing interactive-02 budget."
            ),
            "source_evidence": "Frozen runtime archive; no current local-agent equivalence claim.",
            "word_streaming": False,
            "streaming_notice": (
                "Execution progress followed by validated output; no provider word stream."
            ),
            "archive_sha256": self.review.archive_sha256,
        }

    def ask(self, request: AskRequest) -> UiResult:
        request = AskRequest.model_validate(request.model_dump())
        if request.mode != "live" or request.model_key is not None:
            raise UiError(
                "Accepted Nova runtime accepts only routed AWS questions, without model overrides."
            )
        if Path.cwd().resolve() != self.root:
            raise UiError("Run accepted-runtime questions from the approved checkout root.")
        self._ready_summary()
        with runtime_lease(self.root):
            return self.ledger.execute(request, lambda: self._prepare(request), purpose="question")

    def _prepare(self, request: AskRequest) -> Callable[[SdkAttemptRecorder], UiResult]:
        pool = ReadPool(None, self.ledger.directory / "operator-reads.jsonl")
        try:
            local = self._local_proof()
            pool.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
            checkpoint = verify_release(
                self.shared_review,
                kind="candidate",
                session=pool.view(time.monotonic() + 180, "ui-accepted-release"),
            )
            observed = make_record(self.shared_review, checkpoint, kind="candidate")
            if observed.runtime_version != "15" or observed != self.release.model_copy(
                update={"observed_at": observed.observed_at}
            ):
                raise UiError(
                    "The actual accepted Runtime no longer matches the pinned v15 release."
                )
            publication = verify_publication(
                self.shared_review,
                pool.view(time.monotonic() + 180, "ui-accepted-publication"),
                root=self.root,
            )
            evidence = (
                json.dumps(
                    _redact(
                        {
                            "checkpoint": checkpoint,
                            "release": observed.model_dump(mode="json"),
                            "local": local,
                            "publication": publication,
                            "binding_review_sha256": self.review.sha256,
                            "purpose": "question",
                        }
                    ),
                    indent=2,
                )
                + "\n"
            )
            self.ledger.directory.mkdir(parents=True, exist_ok=True)
            with (self.ledger.directory / f"accepted-preflight-{request.request_id}.json").open(
                "x"
            ) as out:
                out.write(evidence)
            setup = pool.view(time.monotonic() + 30, "ui-accepted-invocation-setup")
            invoke = create_runtime_invoker(
                self.shared_review.target,
                session=pool.session,
                identity_session=setup,
                client_factory=lambda config: setup.invocation_client(
                    runtime_arn=self.shared_review.target.runtime_arn, config=config
                ),
            )
            self._local_proof()
            verify_approval(self.review, self.approval, self.now())
        except BaseException as exc:
            try:
                pool.record(
                    {
                        "event": "ui-accepted-preflight-failed",
                        **error_record(exc, "ui-accepted-preflight"),
                    }
                )
            except Exception:
                pass
            raise UiError(
                "Accepted Runtime preflight failed; no question sent. Inspect operator diagnostics."
            ) from exc

        def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
            started = time.monotonic()
            try:
                verify_approval(self.review, self.approval, self.now())

                def current_invoke(*, payload: bytes, session_id: str) -> object:
                    # The SDK reservation precedes this callback. Recheck the
                    # narrower approval at the actual dispatch boundary too.
                    if operator_source_digest(self.root) != self.review.operator_source_sha256:
                        raise UiError("The approved AWS-only operator source changed.")
                    verify_approval(self.review, self.approval, self.now())
                    return invoke(payload=payload, session_id=session_id)

                reply = recorder.invoke_runtime(
                    current_invoke,
                    payload=AgentRequest(question=request.question).model_dump_json().encode(),
                    session_id=str(uuid4()),
                )
                primary: BaseException | None = None
                try:
                    response = AgentResponse.model_validate_json(reply.body.read())
                except BaseException as exc:
                    primary = exc
                    raise
                finally:
                    try:
                        reply.body.close()
                    except BaseException:
                        if primary is None:
                            raise
                validate_target_response(response, self.shared_review.target)
                if response.diagnostics.configuration != self.shared_review.agent_config.model_dump(
                    mode="json"
                ):
                    raise UiError("The accepted Runtime reported a different model configuration.")
                return UiResult(
                    mode="live",
                    response=response,
                    elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                    unreported_diagnostics=unreported_diagnostics(response),
                )
            except BaseException as exc:
                try:
                    pool.record(
                        {
                            "event": "ui-accepted-dispatch-failed",
                            **error_record(exc, "ui-accepted-dispatch"),
                        }
                    )
                except Exception:
                    pass
                raise

        return dispatch


def main(argv: list[str] | None = None) -> int:
    """Preparation commands never grant approval or dispatch an ordinary question."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-offline")
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--read-only-aws", action="store_true")
    preflight.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parents[3]
        if Path.cwd().resolve() != root:
            raise UiError("Prepare the accepted-runtime binding from the original checkout.")
        review = AcceptedRuntimeReview.model_validate_json(args.review.read_bytes())
        result = (
            verify_offline(root, review)
            if args.command == "verify-offline"
            else verify_read_only(root, review, args.output, read_only_aws=args.read_only_aws)
        )
        print(json.dumps(_redact(result), indent=2))
    except (ValueError, OSError, UiError, zipfile.BadZipFile, SyntaxError) as exc:
        print(f"accepted-runtime: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
