"""A separately reviewed, durable UI allowance. Historical campaigns are never opened."""

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TextIO

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult


class LiveReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["local-ui-live-v1"] = "local-ui-live-v1"
    campaign_id: Annotated[str, Field(pattern=r"^ui-demo-[a-z0-9-]{1,48}$")]
    maximum_calls: Annotated[int, Field(strict=True, ge=1, le=20)]
    expires_at: datetime
    runtime_version: Literal["12"] = "12"
    target: RetailTarget

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review expiry must include a timezone")
        return value.astimezone(UTC)

    @field_validator("target")
    @classmethod
    def original_target_only(cls, target: RetailTarget) -> RetailTarget:
        if target.model_dump(mode="json") != {
            "profile": "analytics-dev",
            "account": "453711491609",
            "region": "us-west-2",
            "runtime_arn": (
                "arn:aws:bedrock-agentcore:us-west-2:453711491609:"
                "runtime/enterprise_analytics_dev_agent-HlWywlG60h"
            ),
            "qualifier": "DEFAULT",
            "model_id": "us.amazon.nova-lite-v1:0",
            "dataset_version": "parity-v1",
            "reference_date": "2025-02-01",
        }:
            raise ValueError("this UI live review supports only the restored original v12 scope")
        return target

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()


class UiAllowanceReview(Protocol):
    @property
    def campaign_id(self) -> str: ...

    @property
    def maximum_calls(self) -> int: ...

    @property
    def expires_at(self) -> datetime: ...

    @property
    def sha256(self) -> str: ...


class UiLedgerFiles:
    def __init__(
        self, root: Path, review: UiAllowanceReview, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self.root, self.review = root.resolve(), review
        self.directory = self.root / "artifacts/ui-demo" / review.campaign_id
        self.path = self.directory / "invocations.jsonl"
        self.claims = self.directory / "reservations"
        self.now = now or (lambda: datetime.now(UTC))
        self._check_paths()

    def _check_paths(self) -> None:
        if self.path.resolve() != self.path or self.claims.resolve() != self.claims:
            raise UiError("The UI ledger path is aliased; preserve it for inspection.")

    @contextmanager
    def _open(self, *, create: bool) -> Iterator[TextIO]:
        self._check_paths()
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
        descriptor = os.open(self.path, flags, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UiError(
                    "Another request owns this UI allowance. Wait for its result."
                ) from exc
            try:
                yield stream
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self, stream: TextIO) -> list[dict[str, Any]]:
        stream.seek(0)
        rows: list[dict[str, Any]] = []
        pending: str | None = None
        seen: set[str] = set()
        closed = False
        for line in stream:
            try:
                row = json.loads(line)
                if not line.endswith("\n") or not isinstance(row, dict):
                    raise ValueError("truncated row")
                if row.get("review_sha256") != self.review.sha256:
                    raise ValueError("changed review")
                request_id = row["request_id"]
                if not isinstance(request_id, str):
                    raise ValueError("invalid request id")
                if row["event"] == "reserved":
                    if pending or closed or request_id in seen:
                        raise ValueError("invalid reservation")
                    seen.add(request_id)
                    if (
                        type(row["number"]) is not int
                        or row["number"] != len(seen)
                        or len(seen) > self.review.maximum_calls
                    ):
                        raise ValueError("invalid count")
                    pending = request_id
                elif row["event"] == "outcome" and request_id == pending:
                    if row["status"] not in {"answer", "clarification", "error", "failed"}:
                        raise ValueError("invalid outcome")
                    closed = row["status"] in {"error", "failed"}
                    if row["status"] != "failed":
                        UiResult.model_validate(row["result"])
                    pending = None
                else:
                    raise ValueError("invalid event order")
                rows.append(row)
            except (ValueError, KeyError, TypeError) as exc:
                raise UiError(
                    "UI ledger is invalid or its review changed. Do not reset it."
                ) from exc
        reservations = [row for row in rows if row["event"] == "reserved"]
        expected = {f"{row['number']}.json": row for row in reservations}
        actual = list(self.claims.iterdir()) if self.claims.exists() else []
        if {path.name for path in actual} != set(expected):
            raise UiError("UI reservation evidence disagrees with its ledger. Do not reset it.")
        for path in actual:
            try:
                if path.resolve() != path or json.loads(path.read_text()) != expected[path.name]:
                    raise ValueError("changed reservation")
            except (ValueError, OSError) as exc:
                raise UiError("UI reservation evidence needs inspection. Do not reset it.") from exc
        return rows

    def _summary(self, rows: list[dict[str, Any]]) -> dict[str, object]:
        reserved = [row for row in rows if row["event"] == "reserved"]
        outcomes = [row for row in rows if row["event"] == "outcome"]
        incomplete = len(reserved) != len(outcomes)
        failed = any(row["status"] in {"error", "failed"} for row in outcomes)
        expired = self.now() >= self.review.expires_at
        used = len(reserved)
        return {
            "campaign_id": self.review.campaign_id,
            "used": used,
            "maximum": self.review.maximum_calls,
            "remaining": self.review.maximum_calls - used,
            "blocked": incomplete or failed or expired or used >= self.review.maximum_calls,
            "incomplete": incomplete,
            "failed": failed,
            "expired": expired,
        }

    def summary(self) -> dict[str, object]:
        self._check_paths()
        if not self.path.exists():
            if self.claims.exists() and any(self.claims.iterdir()):
                raise UiError("The UI ledger is missing but reservation evidence exists.")
            return self._summary([])
        with self._open(create=False) as stream:
            return self._summary(self._read(stream))

    def _append(self, stream: TextIO, value: dict[str, object]) -> None:
        record = {"review_sha256": self.review.sha256, "at": self.now().isoformat(), **value}
        encoded = json.dumps(record, sort_keys=True) + "\n"
        if value["event"] == "reserved":
            self.claims.mkdir(exist_ok=True)
            claim = self.claims / f"{value['number']}.json"
            descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            descriptor = os.open(self.claims, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        stream.seek(0, os.SEEK_END)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class UiLedger(UiLedgerFiles):
    def execute(
        self, request: AskRequest, prepare: Callable[[], Callable[[], UiResult]]
    ) -> UiResult:
        """Prepare read-only first; durably reserve before exactly one dispatch.

        A failed or unknown outcome blocks the allowance. A repeated successful
        request ID returns its saved result without dispatching again.
        """
        request_id = str(request.request_id)
        question_hash = hashlib.sha256(request.question.encode()).hexdigest()
        with self._open(create=True) as stream:
            rows = self._read(stream)
            previous = next((row for row in rows if row["request_id"] == request_id), None)
            if previous is not None:
                if previous["question_sha256"] != question_hash:
                    raise UiError("This request ID already belongs to a different question.")
                outcome = next(
                    (
                        row
                        for row in rows
                        if row["request_id"] == request_id and row["event"] == "outcome"
                    ),
                    None,
                )
                if outcome is not None and outcome["status"] in {"answer", "clarification"}:
                    return UiResult.model_validate(outcome["result"])
                raise UiError("This attempt already exists and cannot be repeated.")
            if self._summary(rows)["blocked"]:
                raise UiError(
                    "This UI allowance is exhausted, expired or blocked. Do not reset it."
                )
            dispatch = prepare()
            if self.now() >= self.review.expires_at:
                raise UiError("The UI allowance expired during preflight; no invocation was sent.")
            number = sum(row["event"] == "reserved" for row in rows) + 1
            self._append(
                stream,
                {
                    "event": "reserved",
                    "request_id": request_id,
                    "number": number,
                    "question_sha256": question_hash,
                },
            )
            try:
                result = dispatch()
            except BaseException:
                self._append(
                    stream, {"event": "outcome", "request_id": request_id, "status": "failed"}
                )
                raise
            self._append(
                stream,
                {
                    "event": "outcome",
                    "request_id": request_id,
                    "status": result.response.status,
                    "result": result.model_dump(mode="json"),
                },
            )
            return result
