"""Explicit, counted UI access to the restored original Runtime; no deployment path."""

import fcntl
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import boto3

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.adapters.retail_checkpoint import verify_checkpoint
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.retail_evaluation.client import validate_target_response
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.ui.live import LiveReview, UiLedger
from enterprise_analytics_agent.ui.models import (
    AskRequest,
    UiError,
    UiResult,
    unreported_diagnostics,
)


@contextmanager
def runtime_lease(root: Path) -> Iterator[None]:
    """Coordinate with the existing operator and deployment guards without rewriting them."""
    directory = root / "artifacts/milestone-5"
    descriptors: list[int] = []
    try:
        for name in ("runtime-operator.lock", "runtime-deployment.lock"):
            path = directory / name
            if path.resolve() != path or not path.is_file():
                raise UiError("Retained Runtime process guards are missing or aliased.")
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UiError("A Runtime operator or deployment is active.") from exc
            if name == "runtime-deployment.lock":
                body = os.read(descriptor, 65537)
                if len(body) > 65536 or not body:
                    raise UiError("Retained deployment journal is unavailable or invalid.")
                try:
                    record = json.loads(body)
                except ValueError as exc:
                    raise UiError("Retained deployment journal is invalid.") from exc
                if not isinstance(record, dict) or record.get("active") is not False:
                    raise UiError("A retained deployment process remains unresolved.")
        yield
    finally:
        for descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


class LiveQuestions:
    def __init__(self, root: Path, review: LiveReview) -> None:
        # Importing/enabling the UI still creates no AWS session or ledger record.
        self.root, self.review = root.resolve(), review
        self.ledger = UiLedger(self.root, review)

    def public_state(self, mode: str) -> dict[str, object]:
        if mode != "live":
            raise UiError("This approved target supports only AWS AgentCore execution.")
        state = self.ledger.summary()
        target = self.review.target
        return {
            "enabled": not state["blocked"],
            "dataset": target.dataset_version,
            "reference_date": target.reference_date.isoformat(),
            "runtime_version": self.review.runtime_version,
            "tenant": "t1",
            "regions": ["North", "South"],
            "description": f"AWS AgentCore · configured target v{self.review.runtime_version}",
            "error": "This live allowance is unavailable." if state["blocked"] else "",
        }

    def ask(self, request: AskRequest) -> UiResult:
        if Path.cwd().resolve() != self.root:
            raise UiError("Live UI must run from the original repository root.")
        with runtime_lease(self.root):
            return self.ledger.execute(request, lambda: self._prepare(request))

    def _prepare(self, request: AskRequest) -> Callable[[], UiResult]:
        target = self.review.target
        pool = ReadPool(None, self.ledger.directory / "operator-reads.jsonl")
        try:
            pool.session = boto3.Session(profile_name=target.profile, region_name=target.region)
            checkpoint = verify_checkpoint(
                scope="parity-v1", session=pool.view(time.monotonic() + 180, "ui-preflight")
            )
            if (
                checkpoint["runtime"]["agentRuntimeArn"] != target.runtime_arn
                or checkpoint["runtime"]["agentRuntimeVersion"] != self.review.runtime_version
                or checkpoint["endpoint"]["liveVersion"] != self.review.runtime_version
            ):
                raise UiError("The Runtime version differs from the reviewed original v12.")
            setup = pool.view(time.monotonic() + 30, "ui-invocation-setup")
            invoke = create_runtime_invoker(
                target,
                session=pool.session,
                identity_session=setup,
                client_factory=lambda config: setup.invocation_client(
                    runtime_arn=target.runtime_arn, config=config
                ),
            )
        except Exception as exc:
            pool.record({"event": "ui-failed", **error_record(exc, "ui-preflight")})
            raise UiError(
                "Live preflight/setup failed; no invocation was sent. Inspect the UI read journal."
            ) from exc

        def dispatch() -> UiResult:
            started = time.monotonic()
            try:
                reply = invoke(
                    payload=AgentRequest(question=request.question).model_dump_json().encode(),
                    session_id=str(uuid4()),
                )
                try:
                    response = AgentResponse.model_validate_json(reply.body.read())
                finally:
                    reply.body.close()
                validate_target_response(response, target)
                return UiResult(
                    mode="live",
                    response=response,
                    elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                    unreported_diagnostics=unreported_diagnostics(response),
                )
            except Exception as exc:
                pool.record({"event": "ui-failed", **error_record(exc, "ui-dispatch")})
                raise UiError(
                    "Live invocation failed and was counted. "
                    "It was not retried; inspect the UI journal."
                ) from exc

        return dispatch
