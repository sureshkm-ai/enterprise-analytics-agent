"""Persistent operator-side M5 quota; reservations are durable before dispatch.

This ledger is separate from the immutable Milestone 4 invocation evidence. An
unfinished reservation still consumes quota: process death cannot erase a call.
"""

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self, TextIO
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

CAMPAIGN_ID = "milestone-5-retail-v1"
MAX_INVOCATIONS = 40
DEFAULT_LEDGER = (
    Path(__file__).resolve().parents[3] / "artifacts/milestone-5/runtime-invocations.jsonl"
)
CODE_SHA256 = "51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1"
CODE_VERSION = "HSRXiFjg0w2W77InULH4.fn32Y.JH8b9"
type Purpose = Literal["warmup", "probe", "case", "session", "demo", "retry", "restoration_smoke"]
type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_PURPOSES = {"warmup", "case", "session", "demo", "retry", "restoration_smoke"}
REPAIR_CAMPAIGN_ID = "milestone-5-q18-repair-v1"
REPAIR_LEDGER = "artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl"


class CampaignError(RuntimeError):
    """Unsafe, corrupted or exhausted campaign state."""


class RepairCampaignBinding(BaseModel):
    """Reviewed repair identity; an uploaded candidate's version record is mandatory.

    Every event carries this exact binding. Changing review, artifact, template or
    uploaded version therefore cannot restart a campaign under an existing ledger.
    The actual source/version verification lives in the operator configuration layer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: Literal["milestone-5-q18-repair-v1"]
    ledger_path: Literal["artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl"]
    maximum: Literal[40]
    review_sha256: Sha256
    candidate_sha256: Sha256
    candidate_template_sha256: Sha256
    candidate_version_record_sha256: Sha256

    @model_validator(mode="after")
    def different_candidate(self) -> Self:
        if self.candidate_sha256 == CODE_SHA256:
            raise ValueError("repair candidate must differ from the original restored artifact")
        return self

    @property
    def sha256(self) -> str:
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()


class RestorationProof(BaseModel):
    """Fresh read-only observations produced by the operator checkpoint verifier.

    There is intentionally no CLI boolean or JSON-file bypass for this proof.
    A restoration invocation obtains it through an injected verifier immediately
    before reserving its call. Equal hashes bind observed state to the checkpoint.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: datetime
    runtime_arn: str
    runtime_status: Literal["READY"]
    endpoint_status: Literal["READY"]
    runtime_version: str
    endpoint_version: str
    dataset_version: Literal["parity-v1"]
    tenant_id: Literal["t1"]
    allowed_regions: tuple[Literal["North"], Literal["South"]]
    reference_date: date
    configuration_sha256: Sha256
    expected_configuration_sha256: Sha256
    template_sha256: Sha256
    expected_template_sha256: Sha256
    code_sha256: Literal["51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1"]
    code_version_id: Literal["HSRXiFjg0w2W77InULH4.fn32Y.JH8b9"]
    resource_policies_verified: Literal[True]
    retention_days: Literal[7]

    @model_validator(mode="after")
    def matching_checkpoint(self) -> Self:
        if self.observed_at.tzinfo is None:
            raise ValueError("restoration timestamp must include a timezone")
        if self.reference_date != date(2025, 2, 1):
            raise ValueError("restoration reference date differs from the approved base")
        if not self.runtime_version or self.runtime_version != self.endpoint_version:
            raise ValueError("Runtime and endpoint must have the same nonempty live version")
        if self.configuration_sha256 != self.expected_configuration_sha256:
            raise ValueError("restored configuration differs from the reviewed checkpoint")
        if self.template_sha256 != self.expected_template_sha256:
            raise ValueError("restored template differs from the corrected checkpoint")
        return self


@dataclass(frozen=True)
class Reservation:
    number: int
    reservation_id: str
    purpose: Purpose


class CampaignLedger:
    def __init__(
        self,
        path: Path | None = None,
        *,
        binding: RepairCampaignBinding | None = None,
        repository_root: Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.binding = (
            RepairCampaignBinding.model_validate(binding.model_dump())
            if binding is not None
            else None
        )
        if self.binding is not None:
            root = (repository_root or Path(__file__).resolve().parents[3]).resolve()
            expected = root / self.binding.ledger_path
            # Refuse both a final symlink and an aliased ancestor directory.
            if expected.resolve() != expected:
                raise CampaignError("repair ledger path must not alias another location")
            selected = path if path is not None else expected
            if selected.absolute() != expected or selected.resolve() != expected:
                raise CampaignError("repair campaign cannot reuse or redirect a historical ledger")
        else:
            if repository_root is not None:
                raise CampaignError("repository_root requires an explicit repair campaign binding")
            selected = path if path is not None else DEFAULT_LEDGER
        self.path = selected.resolve()
        if self.path.parts[-3:] == ("artifacts", "agentcore", "runtime-invocations.jsonl"):
            raise CampaignError("Milestone 4 ledger is immutable; use the separate M5 ledger")
        if self.binding is None and self.path.parts[-4:] == tuple(Path(REPAIR_LEDGER).parts):
            raise CampaignError("repair ledger requires an explicitly pinned campaign binding")
        self.campaign_id = self.binding.campaign_id if self.binding is not None else CAMPAIGN_ID
        self.maximum = self.binding.maximum if self.binding is not None else MAX_INVOCATIONS
        self.purposes = _PURPOSES | {"probe"} if self.binding is not None else _PURPOSES
        self.now = now

    def _identity(self) -> dict[str, object]:
        if self.binding is None:
            return {}
        return {
            "campaign_binding": self.binding.model_dump(mode="json"),
            "campaign_binding_sha256": self.binding.sha256,
        }

    @contextmanager
    def _locked(self) -> Iterator[TextIO]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse symlinks: an alias must not redirect writes into historical evidence.
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield stream
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self, stream: TextIO) -> list[dict[str, object]]:
        stream.seek(0)
        records: list[dict[str, object]] = []
        reservations: dict[str, int] = {}
        completed: set[str] = set()
        restoration_started = False
        for line in stream:
            if not line.endswith("\n"):
                raise CampaignError("incomplete ledger write; preserve it for investigation")
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise CampaignError(
                    "corrupted campaign ledger; preserve it for investigation"
                ) from exc
            if not isinstance(record, dict) or record.get("campaign") != self.campaign_id:
                raise CampaignError("ledger contains a different campaign or malformed entry")
            if self.binding is not None:
                if any(record.get(key) != value for key, value in self._identity().items()):
                    raise CampaignError("ledger repair binding differs from the pinned campaign")
            elif "campaign_binding" in record or "campaign_binding_sha256" in record:
                raise CampaignError("historical campaign cannot contain repair binding records")
            kind = record.get("event")
            reservation_id = record.get("reservation_id")
            if kind == "reserved":
                number = len(reservations) + 1
                if (
                    type(record.get("number")) is not int
                    or number > self.maximum
                    or record.get("number") != number
                    or not isinstance(reservation_id, str)
                    or reservation_id in reservations
                ):
                    raise CampaignError("ledger reservation sequence is invalid")
                if restoration_started and record.get("purpose") != "restoration_smoke":
                    raise CampaignError("ledger contains retail calls after restoration began")
                if (
                    not isinstance(record.get("purpose"), str)
                    or record.get("purpose") not in self.purposes
                ):
                    raise CampaignError("ledger contains an invalid invocation purpose")
                if record.get("purpose") != "restoration_smoke" and number >= self.maximum:
                    raise CampaignError("ledger violated its protected restoration slot")
                if record.get("purpose") == "restoration_smoke":
                    try:
                        proof = RestorationProof.model_validate(record.get("restoration_proof"))
                    except ValueError as exc:
                        raise CampaignError("ledger restoration record lacks valid proof") from exc
                    if proof.runtime_arn != record.get("runtime_arn"):
                        raise CampaignError("ledger restoration proof has the wrong Runtime")
                restoration_started |= record.get("purpose") == "restoration_smoke"
                reservations[reservation_id] = number
            elif kind == "outcome":
                if (
                    not isinstance(reservation_id, str)
                    or reservation_id not in reservations
                    or reservation_id in completed
                ):
                    raise CampaignError("ledger outcome has no unique reservation")
                if not isinstance(record.get("outcome"), str) or record.get("outcome") not in {
                    "answer",
                    "clarification",
                    "error",
                    "failed",
                }:
                    raise CampaignError("ledger contains an invalid outcome")
                completed.add(reservation_id)
            else:
                raise CampaignError("unrecognized campaign ledger event")
            records.append(record)
        return records

    @staticmethod
    def _append(stream: TextIO, record: dict[str, object]) -> None:
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    def reserve(
        self,
        *,
        purpose: Purpose,
        question: str,
        session_id: str,
        runtime_arn: str,
        restoration_proof: RestorationProof | None = None,
    ) -> Reservation:
        proof: dict[str, object] | None = None
        if purpose == "restoration_smoke":
            if restoration_proof is None:
                raise CampaignError("restoration smoke requires freshly verified restored state")
            restoration_proof = RestorationProof.model_validate(restoration_proof.model_dump())
            age = self.now() - restoration_proof.observed_at
            if not timedelta(0) <= age <= timedelta(minutes=5):
                raise CampaignError("restoration verification is stale or future-dated")
            if restoration_proof.runtime_arn != runtime_arn:
                raise CampaignError("restoration proof addresses a different Runtime")
            proof = restoration_proof.model_dump(mode="json")
        elif restoration_proof is not None:
            raise CampaignError("restoration proof cannot authorize a retail invocation")
        if purpose not in self.purposes:
            raise CampaignError("unrecognized invocation purpose")
        with self._locked() as stream:
            records = self._read(stream)
            reserved = [record for record in records if record["event"] == "reserved"]
            if any(record.get("purpose") == "restoration_smoke" for record in reserved):
                if purpose != "restoration_smoke":
                    raise CampaignError("retail dispatch closed after restoration smoke began")
            limit = self.maximum if purpose == "restoration_smoke" else self.maximum - 1
            if len(reserved) >= limit:
                raise CampaignError("campaign budget exhausted; restoration slot is protected")
            reservation = Reservation(len(reserved) + 1, str(uuid4()), purpose)
            self._append(
                stream,
                {
                    "campaign": self.campaign_id,
                    **self._identity(),
                    "event": "reserved",
                    "number": reservation.number,
                    "reservation_id": reservation.reservation_id,
                    "purpose": purpose,
                    "reserved_at": self.now().isoformat(),
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "session_id": session_id,
                    "runtime_arn": runtime_arn,
                    "restoration_proof": proof,
                },
            )
        return reservation

    def finish(
        self,
        reservation: Reservation,
        *,
        outcome: str,
        elapsed_ms: int,
        invocation_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        if outcome not in {"answer", "clarification", "error", "failed"} or elapsed_ms < 0:
            raise CampaignError("invalid invocation outcome or elapsed time")
        with self._locked() as stream:
            records = self._read(stream)
            matching = [
                record
                for record in records
                if record.get("reservation_id") == reservation.reservation_id
            ]
            if len(matching) != 1 or matching[0].get("number") != reservation.number:
                raise CampaignError(
                    "reservation does not belong to this ledger or already completed"
                )
            self._append(
                stream,
                {
                    "campaign": self.campaign_id,
                    **self._identity(),
                    "event": "outcome",
                    "reservation_id": reservation.reservation_id,
                    "outcome": outcome,
                    "elapsed_ms": elapsed_ms,
                    "invocation_id": invocation_id,
                    "error_code": error_code,
                    "completed_at": self.now().isoformat(),
                },
            )

    def summary(self) -> dict[str, object]:
        if not self.path.exists():
            records: list[dict[str, object]] = []
            checksum: str | None = None
        else:
            with self._locked() as stream:
                records = self._read(stream)
                stream.seek(0)
                checksum = hashlib.sha256(stream.read().encode()).hexdigest()
        reserved = [record for record in records if record["event"] == "reserved"]
        outcomes = [record for record in records if record["event"] == "outcome"]
        purposes: dict[str, int] = {}
        errors: dict[str, int] = {}
        for record in reserved:
            purpose = str(record.get("purpose"))
            purposes[purpose] = purposes.get(purpose, 0) + 1
        for record in outcomes:
            if record.get("error_code"):
                code = str(record["error_code"])
                errors[code] = errors.get(code, 0) + 1
        restoration = any(record.get("purpose") == "restoration_smoke" for record in reserved)
        return {
            "campaign": self.campaign_id,
            **self._identity(),
            "used": len(reserved),
            "maximum": self.maximum,
            "completed": len(outcomes),
            "incomplete_reservations": len(reserved) - len(outcomes),
            "remaining": self.maximum - len(reserved),
            "failures": sum(record.get("outcome") in {"failed", "error"} for record in outcomes),
            "purposes": purposes,
            "error_codes": errors,
            "timeouts": sum(count for code, count in errors.items() if code.endswith("_timeout")),
            "retries": purposes.get("retry", 0),
            "retail_closed": restoration,
            "protected_restoration_slots": 0 if restoration else 1,
            "ledger_sha256": checksum,
        }
