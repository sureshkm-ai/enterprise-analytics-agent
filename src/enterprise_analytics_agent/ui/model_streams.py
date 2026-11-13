"""Reviewed multi-model streaming scope and a separate durable attempt journal.

No AWS clients, historical ledger changes, or approval inference live here.
"""

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_analytics_agent.adapters.bedrock_model_catalog import get_model
from enterprise_analytics_agent.hosting.config import RuntimeSettings
from enterprise_analytics_agent.ui.models import UiError
from enterprise_analytics_agent.ui.streaming_health import accepted_model, request_failures


class StreamTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_key: str
    runtime_name: Annotated[str, Field(pattern=r"^enterprise_analytics_stream_[a-z0-9_]+$")]
    settings: RuntimeSettings
    template_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def reviewed_scope(self) -> Self:
        model = get_model(self.model_key)
        if (
            self.settings.model_id != model.model_id
            or self.settings.account != "453711491609"
            or self.settings.region != "us-west-2"
            or self.settings.tenant_id != "retail_demo"
            or self.settings.allowed_regions != ("North", "South")
            or self.settings.reference_date.isoformat() != "2025-04-01"
            or self.settings.dataset_version != "retail-v1"
            or self.settings.max_iterations != 5
            or self.settings.max_total_tokens != 12000
            or self.settings.database != "enterprise_analytics_dev"
            or self.settings.workgroup != "enterprise-analytics-dev"
            or self.settings.source_bucket != "enterprise-analytics-dev-453711491609-us-west-2-data"
            or self.settings.results_bucket
            != "enterprise-analytics-dev-453711491609-us-west-2-results"
            or self.settings.table_prefix != "ea"
            or self.settings.max_tool_calls != 16
            or self.settings.max_output_tokens != 1024
            or self.settings.timeout_seconds != 90
            or self.settings.query_timeout_seconds != 60
            or self.settings.query_role_arn
            != ("arn:aws:iam::453711491609:role/enterprise-analytics-dev-query-executor")
        ):
            raise ValueError("The streaming target differs from the proposed governed scope.")
        return self


class StreamingParent(BaseModel):
    """Read-only binding to the closed attempt that funds one continuation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    campaign_id: Annotated[str, Field(pattern=r"^bedrock-stream-[a-z0-9-]{1,48}$")]
    review_path: str
    review_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    journal_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    acceptance_claim_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    inventory_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    prior_used: Literal[3] = 3
    aggregate_maximum: Literal[40] = 40

    @model_validator(mode="after")
    def relative_review(self) -> Self:
        path = Path(self.review_path)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != self.review_path:
            raise ValueError("The parent review must be an unaliased repository-relative path.")
        return self


class StreamingReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[
        "bedrock-model-stream-v1",
        "bedrock-model-stream-continuation-v1",
        "bedrock-model-workbench-v1",
    ] = "bedrock-model-stream-v1"
    campaign_id: Annotated[str, Field(pattern=r"^bedrock-stream-[a-z0-9-]{1,48}$")]
    profile: Literal["analytics-dev"] = "analytics-dev"
    account: Literal["453711491609"] = "453711491609"
    region: Literal["us-west-2"] = "us-west-2"
    expires_at: datetime
    maximum_attempts: Annotated[int, Field(strict=True, ge=2, le=40)] = 40
    ordinary_limit: Annotated[int, Field(strict=True, ge=0, le=38)] = 38
    # Omission, rather than serialized null, preserves every existing v1 digest.
    parent: StreamingParent | None = Field(default=None, exclude_if=lambda value: value is None)
    artifact_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    artifact_bytes: Annotated[int, Field(gt=0)]
    artifact_path: str
    artifact_key: str
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    canonical_manifest_sha256: Literal[
        "99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797"
    ]
    targets: Annotated[tuple[StreamTarget, ...], Field(min_length=1, max_length=11)]

    @model_validator(mode="after")
    def immutable_scope(self) -> Self:
        if self.schema_version == "bedrock-model-stream-v1":
            if self.parent is not None or (self.maximum_attempts, self.ordinary_limit) != (40, 38):
                raise ValueError("The original streaming review keeps its exact 40/38 scope.")
        elif self.schema_version == "bedrock-model-workbench-v1":
            if self.parent is not None or self.ordinary_limit != self.maximum_attempts - 2:
                raise ValueError("A workbench review reserves cleanup and one unused reserve.")
        elif (
            self.parent is None
            or self.parent.campaign_id == self.campaign_id
            or (self.maximum_attempts, self.ordinary_limit) != (37, 35)
        ):
            raise ValueError("The continuation needs its closed parent and exact 37/35 scope.")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("The streaming expiry must include a timezone.")
        if self.artifact_key != f"releases/{self.artifact_sha256}/agent.zip":
            raise ValueError("The upload key must bind the new artifact checksum.")
        if len({target.model_key for target in self.targets}) != len(self.targets):
            raise ValueError("Streaming model keys must be unique.")
        if len({target.runtime_name for target in self.targets}) != len(self.targets):
            raise ValueError("Each fixed model needs a distinct runtime target.")
        return self

    @property
    def sha256(self) -> str:
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(content).hexdigest()


class StreamRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_key: str
    runtime_arn: Annotated[
        str,
        Field(
            pattern=(
                r"^arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
                r"enterprise_analytics_stream_[a-z0-9_]+-[A-Za-z0-9]+$"
            )
        ),
    ]
    runtime_version: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
    configuration_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    template_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class StreamingReleases(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    review_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    artifact_version_id: Annotated[str, Field(min_length=1, max_length=1024)]
    models: tuple[StreamRelease, ...]

    def validate_review(self, review: StreamingReview) -> None:
        if self.review_sha256 != review.sha256:
            raise UiError("The streaming release set does not match the reviewed scope.")
        if {model.model_key for model in self.models} != {t.model_key for t in review.targets}:
            raise UiError("The actual release set is missing or duplicates a reviewed model.")
        if len(self.models) != len(review.targets):
            raise UiError("The actual release set contains duplicate model bindings.")
        for target in review.targets:
            record = next(item for item in self.models if item.model_key == target.model_key)
            if not record.runtime_arn.rsplit("/", 1)[1].startswith(target.runtime_name + "-"):
                raise UiError("A model release points to a different runtime.")
            if record.template_sha256 != target.template_sha256:
                raise UiError("A streaming release differs from the reviewed template checksum.")
            digest = hashlib.sha256(
                json.dumps(target.settings.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
            if record.configuration_sha256 != digest:
                raise UiError("A streaming release configuration checksum differs.")


def verify_approval(review: StreamingReview, approval: object, *, now: datetime) -> None:
    if (
        not isinstance(approval, dict)
        or approval.get("review_sha256") != review.sha256
        or approval.get("approved") is not True
        or approval.get("maximum_attempts") != review.maximum_attempts
        or approval.get("expires_at") != review.expires_at.isoformat()
        or now >= review.expires_at
    ):
        raise UiError("A current explicit approval for this exact streaming scope is required.")


class StreamingLedger:
    """One new journal/receipt namespace; old campaigns are never opened for writing."""

    def __init__(
        self, root: Path, review: StreamingReview, *, recover_requests: bool = False
    ) -> None:
        if recover_requests and review.schema_version != "bedrock-model-workbench-v1":
            raise UiError("Request recovery cannot reopen historical campaigns.")
        self.root, self.review = root.resolve(), review
        self.recover_requests = recover_requests
        self.directory = self.root / "artifacts/bedrock-streaming" / review.campaign_id
        self.path = self.directory / "attempts.jsonl"
        self.claims = self.directory / "reservations"
        self.sdk_claims = self.directory / "sdk-reservations"

    def _paths(self) -> None:
        for path in (self.directory, self.path, self.claims, self.sdk_claims):
            if path.resolve() != path:
                raise UiError("Streaming evidence paths must not be aliased.")

    @property
    def continuation_claim_path(self) -> Path | None:
        parent = self.review.parent
        if parent is None:
            return None
        return (
            self.root
            / "artifacts/bedrock-streaming/continuation-claims"
            / f"{parent.campaign_id}.json"
        )

    def _claim_binding(self) -> dict[str, object]:
        parent = self.review.parent
        if parent is None:
            return {}
        return {
            "schema_version": "bedrock-stream-continuation-claim-v1",
            "parent_campaign_id": parent.campaign_id,
            "parent_review_sha256": parent.review_sha256,
            "parent_journal_sha256": parent.journal_sha256,
            "parent_acceptance_claim_sha256": parent.acceptance_claim_sha256,
            "parent_inventory_sha256": parent.inventory_sha256,
            "campaign_id": self.review.campaign_id,
            "review_sha256": self.review.sha256,
            "prior_used": parent.prior_used,
            "maximum_attempts": self.review.maximum_attempts,
            "ordinary_limit": self.review.ordinary_limit,
            "aggregate_maximum": parent.aggregate_maximum,
            "expires_at": self.review.expires_at.isoformat(),
        }

    def _continuation_claim(self, *, create: bool = False, exclusive: bool = False) -> bool:
        path = self.continuation_claim_path
        if path is None:
            return False
        if path.parent.resolve() != path.parent or path.resolve() != path:
            raise UiError("The continuation claim path must not be aliased.")
        expected = self._claim_binding()
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(
                    path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                if exclusive:
                    raise UiError(
                        "The continuation was already claimed; inspect its retained operation."
                    ) from None
            else:
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(
                        json.dumps(
                            {**expected, "claimed_at": datetime.now(UTC).isoformat()},
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        if not path.exists():
            if self.path.exists() or self.claims.exists() or self.sdk_claims.exists():
                raise UiError("The continuation claim is missing; preserve the child journal.")
            return False
        try:
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict) or set(value) != {*expected, "claimed_at"}:
                raise ValueError("claim fields differ")
            claimed_at = datetime.fromisoformat(value["claimed_at"])
            if (
                any(value[key] != item for key, item in expected.items())
                or claimed_at.tzinfo is None
                or claimed_at.utcoffset() is None
                or claimed_at >= self.review.expires_at
            ):
                raise ValueError("claim binding differs")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise UiError(
                "The parent allowance is claimed by a different or damaged continuation."
            ) from exc
        return True

    def _validate_parent(self) -> None:
        """Inspect the complete closed parent with no directories or counters created."""
        binding = self.review.parent
        if binding is None:
            return
        try:
            review_path = self.root / binding.review_path
            if review_path.resolve() != review_path or not review_path.is_relative_to(self.root):
                raise ValueError("parent review path differs")
            parent_review = StreamingReview.model_validate_json(review_path.read_bytes())
            if (
                parent_review.schema_version != "bedrock-model-stream-v1"
                or parent_review.sha256 != binding.review_sha256
                or parent_review.campaign_id != binding.campaign_id
                or self.review.expires_at > parent_review.expires_at
            ):
                raise ValueError("parent review binding differs")
            expected_targets = {
                target.model_key: (target.runtime_name, target.settings.model_dump(mode="json"))
                for target in parent_review.targets
            }
            actual_targets = {
                target.model_key: (target.runtime_name, target.settings.model_dump(mode="json"))
                for target in self.review.targets
            }
            if expected_targets != actual_targets:
                raise ValueError("continuation changes the reviewed model or trusted scope")
            parent = StreamingLedger(self.root, parent_review)
            parent._paths()
            if (
                hashlib.sha256(parent.path.read_bytes()).hexdigest() != binding.journal_sha256
                or hashlib.sha256(
                    (parent.directory / "acceptance-claim.json").read_bytes()
                ).hexdigest()
                != binding.acceptance_claim_sha256
            ):
                raise ValueError("parent journal or attempt claim changed")
            inventory = {}
            for item in sorted(parent.directory.rglob("*")):
                if item.is_symlink() or item.resolve() != item:
                    raise ValueError("parent inventory aliases another location")
                if item.is_file():
                    inventory[str(item.relative_to(parent.directory))] = hashlib.sha256(
                        item.read_bytes()
                    ).hexdigest()
            if (
                hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
                != binding.inventory_sha256
            ):
                raise ValueError("the closed parent inventory changed")
            claim = json.loads((parent.directory / "acceptance-claim.json").read_bytes())
            state = parent.summary()
            rows = parent._rows()
            cleanup = next(
                row for row in rows if row["event"] == "reserved" and row["purpose"] == "cleanup"
            )
            cleanup_passed = any(
                row["event"] == "outcome"
                and row["request_id"] == cleanup["request_id"]
                and row["status"] == "complete"
                for row in rows
            )
            if (
                claim.get("review_sha256") != parent_review.sha256
                or state["used"] != binding.prior_used
                or not state["failed"]
                or not state["blocked"]
                or state["incomplete"]
                or state["protected_cleanup"] != 0
                or not cleanup_passed
            ):
                raise ValueError("the parent is not the reviewed closed three-call attempt")
            self._continuation_claim()
        except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
            raise UiError(
                "The closed streaming parent requires inspection; no call was sent."
            ) from exc

    def claim_continuation(self, approval: object) -> None:
        """Claim the approved child before deployment, without touching its parent.

        The operator holds its existing global runtime lease around deployment.
        Exclusive creation also prevents a second child selector from spending
        the same parent allowance through a separate question lock.
        """
        verify_approval(self.review, approval, now=datetime.now(UTC))
        self._validate_parent()
        if self.review.parent is not None:
            self._continuation_claim(create=True, exclusive=True)

    def _rows(self) -> list[dict[str, Any]]:
        try:
            return self._read_rows()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise UiError("The streaming journal requires inspection; do not reset it.") from exc

    def _read_rows(self) -> list[dict[str, Any]]:
        self._paths()
        self._validate_parent()
        rows = []
        receipts = set(self.claims.glob("*.json")) if self.claims.exists() else set()
        sdk_receipts = set(self.sdk_claims.glob("*.json")) if self.sdk_claims.exists() else set()
        if not self.path.exists():
            if receipts or sdk_receipts:
                raise UiError("Streaming journal is missing; preserve its existing receipts.")
            return []
        for line in self.path.read_text().splitlines(keepends=True):
            if not line.endswith("\n"):
                raise UiError("Streaming journal is truncated; do not reset it.")
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("review_sha256") != self.review.sha256:
                raise UiError("Streaming journal/review binding differs.")
            if row.get("event") not in {
                "reserved",
                "outcome",
                "failure",
                "sdk_reserved",
                "sdk_returned",
                "sdk_failed",
            }:
                raise UiError("Unknown streaming journal event.")
            if str(UUID(row["request_id"])) != row["request_id"]:
                raise UiError("Invalid streaming request identifier.")
            rows.append(row)
        reservations = [row for row in rows if row.get("event") == "reserved"]
        expected = {self.claims / f"{row['request_id']}.json" for row in reservations}
        if len({row["request_id"] for row in reservations}) != len(reservations):
            raise UiError("Streaming reservations are duplicated.")
        if expected != receipts:
            raise UiError("Streaming reservation inventory differs; do not reset it.")
        for row in reservations:
            receipt = self.claims / f"{row['request_id']}.json"
            if receipt.resolve() != receipt or json.loads(receipt.read_bytes()) != row:
                raise UiError("Streaming reservation receipt differs.")
        requests: dict[str, dict[str, Any]] = {}
        sdk: dict[tuple[str, int], dict[str, Any]] = {}
        failed_requests: set[str] = set()
        completed = set()
        for row in rows:
            if row["event"] == "reserved":
                if row.get("mode") not in {"local_agent", "live"} or row.get("purpose") not in {
                    "question",
                    "cleanup",
                }:
                    raise UiError("Invalid streaming reservation mode or purpose.")
                requests[row["request_id"]] = row
                continue
            if row["request_id"] not in requests or row["request_id"] in completed:
                raise UiError("Streaming event is unbound or follows its outcome.")
            if row["event"] == "outcome":
                if row.get("status") not in {"complete", "failed"}:
                    raise UiError("Invalid streaming outcome.")
                completed.add(row["request_id"])
                continue
            if not row["event"].startswith("sdk_"):
                if row["event"] == "failure":
                    failed_requests.add(row["request_id"])
                continue
            mode = requests[row["request_id"]]["mode"]
            number = row.get("number")
            if type(number) is not int or not 1 <= number <= (6 if mode == "local_agent" else 1):
                raise UiError("Streaming SDK call ceiling or number differs.")
            key = (row["request_id"], number)
            operation = row.get("operation")
            allowed = (
                {"Converse", "ConverseStream", "ChatCompletions", "ChatCompletionsStream"}
                if mode == "local_agent"
                else {"InvokeAgentRuntime"}
            )
            if operation not in allowed:
                raise UiError("SDK operation does not match the streaming question mode.")
            if row["event"] == "sdk_reserved":
                previous = [item for item in sdk if item[0] == key[0]]
                if key in sdk or number != len(previous) + 1 or key[0] in failed_requests:
                    raise UiError("Streaming SDK reservation is duplicated or reordered.")
                sdk[key] = row
            elif key not in sdk or sdk[key].get("done") or sdk[key]["operation"] != operation:
                raise UiError("Streaming SDK outcome is duplicated or unbound.")
            else:
                sdk[key] = {**sdk[key], "done": True}
                if row["event"] == "sdk_failed":
                    failed_requests.add(key[0])
        expected_sdk = {self.sdk_claims / f"{key[0]}-{key[1]}.json" for key in sdk}
        if sdk_receipts != expected_sdk:
            raise UiError("Streaming SDK reservation inventory differs; do not reset it.")
        for (identifier, number), row in sdk.items():
            receipt = self.sdk_claims / f"{identifier}-{number}.json"
            original = {key: value for key, value in row.items() if key != "done"}
            if receipt.resolve() != receipt or json.loads(receipt.read_bytes()) != original:
                raise UiError("Streaming SDK reservation receipt differs.")
        return rows

    def summary(self) -> dict[str, object]:
        rows = self._rows()
        reserved = [row for row in rows if row["event"] == "reserved"]
        outcomes = [row for row in rows if row["event"] == "outcome"]
        identifiers = {row["request_id"] for row in reserved}
        finished = {row["request_id"] for row in outcomes}
        if len(finished) != len(outcomes) or not finished <= identifiers:
            raise UiError("Streaming outcomes are duplicated or unbound.")
        used = len(reserved)
        failed = any(row.get("status") == "failed" for row in outcomes) or any(
            row["event"] in {"sdk_failed", "failure"} for row in rows
        )
        ordinary = sum(row["purpose"] == "question" for row in reserved)
        cleanup_used = sum(row["purpose"] == "cleanup" for row in reserved)
        incomplete = identifiers != finished
        sdk_started = {
            (row["request_id"], row["number"]) for row in rows if row["event"] == "sdk_reserved"
        }
        sdk_ended = {
            (row["request_id"], row["number"])
            for row in rows
            if row["event"] in {"sdk_returned", "sdk_failed"}
        }
        incomplete = incomplete or sdk_started != sdk_ended
        expired = datetime.now(UTC) >= self.review.expires_at
        failed_requests = {
            row["request_id"]
            for row in rows
            if row["event"] in {"sdk_failed", "failure"} or row.get("status") == "failed"
        }
        blocked_models = sorted(
            {
                row["model_key"]
                for row in reserved
                if row["request_id"] in failed_requests and row["purpose"] == "question"
            }
        )
        isolated = self.review.schema_version == "bedrock-model-workbench-v1"
        state: dict[str, object] = {
            "used": used,
            "maximum": self.review.maximum_attempts,
            "ordinary_used": ordinary,
            "regular_remaining": max(0, self.review.ordinary_limit - ordinary),
            "protected_cleanup": 1 - cleanup_used,
            "unapproved_reserve": 1,
            "failed": failed,
            "incomplete": incomplete,
            "expired": expired,
            "blocked": (failed and not isolated)
            or incomplete
            or expired
            or cleanup_used > 0
            or ordinary >= self.review.ordinary_limit,
        }
        if isolated:
            if self.recover_requests:
                failures = request_failures(
                    self.directory,
                    rows,
                    {target.model_key: target.settings.model_id for target in self.review.targets},
                    now=datetime.now(UTC),
                )
                blocked_models = sorted(
                    {
                        item["model_key"]
                        for item in failures
                        if not item["recoverable"]
                        or item["wait_seconds"]
                        or not accepted_model(self.directory, self.review.sha256, item["model_key"])
                    }
                )
                state["request_failures"] = failures
                state["request_recovery"] = "accepted-models-only; manual submissions; no retries"
            state["blocked_models"] = blocked_models
            state["failure_scope"] = "model"
        if self.review.parent is not None:
            if used > self.review.maximum_attempts - 1 or ordinary > self.review.ordinary_limit:
                raise UiError("The continuation journal exceeds its approved remaining allowance.")
            state.update(
                prior_used=self.review.parent.prior_used,
                aggregate_used=self.review.parent.prior_used + used,
                aggregate_maximum=self.review.parent.aggregate_maximum,
                continuation_claimed=self._continuation_claim(),
            )
        return state

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._paths()
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.directory / "question.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UiError("Another streaming question is still running.") from exc
            yield
        finally:
            os.close(descriptor)

    def _append(self, row: dict[str, object]) -> None:
        self._paths()
        row = {"at": datetime.now(UTC).isoformat(), "review_sha256": self.review.sha256, **row}
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @contextmanager
    def attempt(
        self,
        request_id: str,
        model_key: str,
        *,
        mode: Literal["local_agent", "live"],
        cleanup: bool = False,
    ) -> Iterator[Callable[[dict[str, object]], None]]:
        if str(UUID(request_id)) != request_id or model_key not in {
            target.model_key for target in self.review.targets
        }:
            raise UiError("Invalid streaming attempt or model binding.")
        self._validate_parent()
        with self._locked():
            state = self.summary()
            used = state["used"]
            if not isinstance(used, int):
                raise UiError("The streaming journal has an invalid attempt count.")
            blocked_models = state.get("blocked_models", [])
            ordinary_blocked = (
                state["blocked"]
                or used >= self.review.ordinary_limit
                or (isinstance(blocked_models, list) and model_key in blocked_models)
            )
            if (
                datetime.now(UTC) >= self.review.expires_at
                or (cleanup and (state["protected_cleanup"] != 1 or mode != "live"))
                or (not cleanup and ordinary_blocked)
                or used >= self.review.maximum_attempts - 1
            ):
                raise UiError("The streaming allowance is closed; no call was sent.")
            if self.review.parent is not None:
                self._continuation_claim(create=True)
            self.claims.mkdir(exist_ok=True)
            reservation = {
                "at": datetime.now(UTC).isoformat(),
                "review_sha256": self.review.sha256,
                "event": "reserved",
                "request_id": request_id,
                "model_key": model_key,
                "purpose": "cleanup" if cleanup else "question",
                "mode": mode,
            }
            receipt = self.claims / f"{request_id}.json"
            descriptor = os.open(
                receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w") as stream:
                stream.write(json.dumps(reservation, sort_keys=True))
                stream.flush()
                os.fsync(stream.fileno())
            # Append the exact receipt, including its timestamp.
            descriptor = os.open(
                self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "a") as stream:
                stream.write(json.dumps(reservation, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            for directory in (self.claims, self.directory):
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

            failure = False
            closed = False

            def record(event: dict[str, object]) -> None:
                nonlocal failure
                if closed:
                    raise UiError("This streaming attempt is closed; no call was sent.")
                rows = self._rows()
                if event["event"] == "question_failed":
                    failure = True
                    self._append({"event": "failure", "request_id": request_id})
                    return
                # Reconcile evidence before and after every SDK event. A missing
                # journal or edited receipt can never restart a call count.
                allowed = (
                    {"Converse", "ConverseStream", "ChatCompletions", "ChatCompletionsStream"}
                    if mode == "local_agent"
                    else {"InvokeAgentRuntime"}
                )
                if event.get("operation") not in allowed or event.get("event") not in {
                    "reserved",
                    "returned",
                    "failed",
                }:
                    raise UiError("Invalid streaming SDK operation or event.")
                number = event.get("number")
                own = [row for row in rows if row["request_id"] == request_id]
                starts = [row for row in own if row["event"] == "sdk_reserved"]
                ends = [row for row in own if row["event"] in {"sdk_returned", "sdk_failed"}]
                if type(number) is not int or not 1 <= number <= (
                    6 if mode == "local_agent" else 1
                ):
                    raise UiError("Streaming SDK call ceiling reached; no call was sent.")
                row = {
                    "at": datetime.now(UTC).isoformat(),
                    "review_sha256": self.review.sha256,
                    **event,
                    "event": "sdk_" + str(event["event"]),
                    "request_id": request_id,
                }
                if event["event"] == "reserved":
                    if datetime.now(UTC) >= self.review.expires_at:
                        raise UiError("The streaming expiry was reached; no call was sent.")
                    if (
                        number != len(starts) + 1
                        or len(starts) != len(ends)
                        or failure
                        or any(item["event"] == "sdk_failed" for item in own)
                    ):
                        raise UiError("A reserved or failed SDK call cannot be replayed.")
                    self.sdk_claims.mkdir(exist_ok=True)
                    path = self.sdk_claims / f"{request_id}-{number}.json"
                    descriptor = os.open(
                        path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                    )
                    with os.fdopen(descriptor, "w") as stream:
                        stream.write(json.dumps(row, sort_keys=True))
                        stream.flush()
                        os.fsync(stream.fileno())
                    for directory in (self.sdk_claims, self.directory):
                        descriptor = os.open(directory, os.O_RDONLY)
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                elif (
                    not starts
                    or number != len(starts)
                    or len(ends) != len(starts) - 1
                    or starts[-1]["operation"] != event["operation"]
                ):
                    raise UiError("Streaming SDK outcome is duplicated or unbound.")
                descriptor = os.open(self.path, os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "a") as stream:
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self._rows()

            try:
                yield record
            except BaseException:
                self._append({"event": "outcome", "request_id": request_id, "status": "failed"})
                raise
            else:
                self._append(
                    {
                        "event": "outcome",
                        "request_id": request_id,
                        "status": "failed" if failure else "complete",
                    }
                )
            finally:
                closed = True
