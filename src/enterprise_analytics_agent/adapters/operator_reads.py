"""Deadline-bound recovery and diagnostics for allowlisted operator reads only."""

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

# One retry owner. No environment setting can add hidden SDK attempts.
READ_CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1})
READS = {
    "sts": {"get_caller_identity"},
    "s3": {"head_object", "list_objects_v2"},
    "glue": {"get_table"},
    "cloudformation": {"describe_stacks", "get_template"},
    "bedrock-agentcore-control": {
        "get_agent_runtime",
        "get_agent_runtime_endpoint",
        "get_resource_policy",
    },
    "logs": {"describe_log_groups"},
}
TRANSIENT_CODES = {
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "SlowDown",
    "ServiceUnavailable",
    "ServiceUnavailableException",
    "InternalError",
    "InternalFailure",
    "InternalServerException",
    "RequestTimeout",
    "RequestTimeoutException",
    "ThrottledException",
    "RequestThrottledException",
    "InternalServerError",
}
TARGET_FIELDS = {
    "StackName",
    "CatalogId",
    "DatabaseName",
    "Name",
    "Prefix",
    "agentRuntimeId",
    "endpointName",
    "resourceArn",
    "Bucket",
    "Key",
    "VersionId",
    "logGroupNamePrefix",
}


class OperatorReadError(RuntimeError):
    """Safe context survives exception chaining through controller and workflow."""

    def __init__(self, diagnostic: dict[str, Any]) -> None:
        self.diagnostic = diagnostic
        super().__init__(
            f"{diagnostic['phase']}: {diagnostic['service']}.{diagnostic['operation']} "
            f"{diagnostic['error_type']} after {diagnostic['attempt']} attempt(s)"
        )


class ReadDeadlineError(OperatorReadError, TimeoutError):
    """A scheduling deadline expired before/after a bounded SDK read."""


def _failure(exc: BaseException) -> dict[str, Any]:
    result: dict[str, Any] = {"error_type": type(exc).__name__}
    if isinstance(exc, ClientError):
        metadata = exc.response.get("ResponseMetadata", {})
        result.update(
            aws_error_code=exc.response.get("Error", {}).get("Code"),
            request_id=metadata.get("RequestId"),
            http_status=metadata.get("HTTPStatusCode"),
        )
    endpoint = getattr(exc, "kwargs", {}).get("endpoint_url")
    if isinstance(endpoint, str):
        try:
            result["failure_endpoint_host"] = urlsplit(endpoint).hostname
        except ValueError:
            pass
    # Raw exception strings/URLs can include signed requests or sensitive payloads.
    return result


def _transient(exc: BaseException) -> bool:
    if isinstance(
        exc, (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError, ConnectionClosedError)
    ):
        return True
    return isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in (
        TRANSIENT_CODES
    )


class ReadPool:
    """Reuse connections across verification stages, with durable per-attempt evidence."""

    def __init__(
        self,
        session: Any,
        journal: Path | None = None,
        *,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.session, self.journal = session, journal
        self.clock, self.sleep = monotonic or time.monotonic, sleep or time.sleep
        self.clients: dict[str, Any] = {}

    def record(self, value: dict[str, Any]) -> None:
        if self.journal is None:
            return
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "a") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **value}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def view(self, deadline: float, phase: str) -> "ReadSession":
        return ReadSession(self, deadline, phase)


class ReadSession:
    def __init__(self, pool: ReadPool, deadline: float, phase: str) -> None:
        self.pool, self.deadline, self.phase = pool, deadline, phase

    def client(self, name: str, **kwargs: Any) -> Any:
        if name not in READS:
            raise ValueError("service is outside the operator read allowlist")
        if self.pool.clock() >= self.deadline:
            raise TimeoutError("checkpoint client budget exhausted")
        if name not in self.pool.clients:
            context: dict[str, Any] = {
                "phase": self.phase,
                "service": name,
                "operation": "create_client",
                "attempt": 0,
            }
            self.pool.record({**context, "event": "started"})
            try:
                kwargs["config"] = READ_CONFIG
                self.pool.clients[name] = self.pool.session.client(name, **kwargs)
            except Exception as exc:
                failure = {**context, **_failure(exc)}
                self.pool.record({**failure, "event": "failed"})
                raise OperatorReadError(failure) from exc
            self.pool.record({**context, "event": "succeeded"})
        if self.pool.clock() >= self.deadline:
            raise TimeoutError("checkpoint client exceeded its budget")
        return ReadClient(self, name, self.pool.clients[name])

    def invocation_client(self, *, runtime_arn: str, config: Config) -> Any:
        """Journal one client construction and return the unwrapped SDK client.

        Credential resolution can outlast the scheduling deadline. Reject late
        setup before permitting dispatch; never retry construction or invocation.
        This client must not enter the read pool or acquire its read retry loop.
        """
        retries = getattr(config, "retries", None)
        if not isinstance(retries, dict) or retries.get("total_max_attempts") != 1:
            raise ValueError("Runtime invocation client requires exactly one SDK attempt")
        context: dict[str, Any] = {
            "phase": self.phase,
            "service": "bedrock-agentcore",
            "operation": "create_client",
            "attempt": 1,
            "endpoint_host": None,
            "region": "us-west-2",
            "target": {"agentRuntimeArn": runtime_arn},
        }
        if self.pool.clock() >= self.deadline:
            failure = {**context, "attempt": 0, "error_type": "client budget exhausted"}
            self.pool.record({**failure, "event": "failed", "will_retry": False})
            raise ReadDeadlineError(failure)
        started = self.pool.clock()
        self.pool.record({**context, "event": "started"})
        try:
            client = self.pool.session.client("bedrock-agentcore", config=config)
        except BaseException as exc:
            failure = {
                **context,
                **_failure(exc),
                "elapsed_seconds": round(self.pool.clock() - started, 6),
            }
            self.pool.record({**failure, "event": "failed", "will_retry": False})
            if not isinstance(exc, Exception):
                raise
            raise OperatorReadError(failure) from exc
        endpoint = getattr(getattr(client, "meta", None), "endpoint_url", "")
        context["endpoint_host"] = (
            urlsplit(endpoint).hostname if isinstance(endpoint, str) else None
        )
        context["elapsed_seconds"] = round(self.pool.clock() - started, 6)
        if self.pool.clock() >= self.deadline:
            failure = {**context, "error_type": "client setup exceeded its budget"}
            self.pool.record({**failure, "event": "failed", "will_retry": False})
            raise ReadDeadlineError(failure)
        self.pool.record({**context, "event": "succeeded"})
        return client


class ReadClient:
    def __init__(self, session: ReadSession, service: str, client: Any) -> None:
        self.session, self.service, self.client = session, service, client

    def __getattr__(self, operation: str) -> Any:
        if operation not in READS[self.service]:
            raise ValueError("operation is outside the operator read allowlist")
        method = getattr(self.client, operation)

        def call(*args: Any, **kwargs: Any) -> Any:
            pool, deadline = self.session.pool, self.session.deadline
            endpoint = getattr(getattr(self.client, "meta", None), "endpoint_url", "")
            host = urlsplit(endpoint).hostname if isinstance(endpoint, str) else None
            context: dict[str, Any] = {
                "phase": self.session.phase,
                "service": self.service,
                "operation": operation,
                "endpoint_host": host,
                "region": "us-west-2",
                "target": {
                    key: value
                    for key, value in kwargs.items()
                    if key in TARGET_FIELDS and isinstance(value, str)
                },
            }
            for attempt in range(1, 4):
                if pool.clock() >= deadline:
                    failure = {
                        **context,
                        "attempt": attempt - 1,
                        "error_type": "read budget exhausted",
                    }
                    pool.record({**failure, "event": "failed", "will_retry": False})
                    raise ReadDeadlineError(failure)
                started = pool.clock()
                pool.record({**context, "event": "started", "attempt": attempt})
                try:
                    result = method(*args, **kwargs)
                except BaseException as exc:
                    failure = {
                        **context,
                        "attempt": attempt,
                        **_failure(exc),
                        "elapsed_seconds": round(pool.clock() - started, 6),
                    }
                    delay = 0.5 * 2 ** (attempt - 1)
                    retry = _transient(exc) and attempt < 3 and pool.clock() + delay < deadline
                    pool.record({**failure, "event": "failed", "will_retry": retry})
                    if not isinstance(exc, Exception):
                        raise
                    if not retry:
                        raise OperatorReadError(failure) from exc
                    pool.sleep(delay)
                    continue
                if pool.clock() >= deadline:
                    failure = {
                        **context,
                        "attempt": attempt,
                        "error_type": "read exceeded its budget",
                    }
                    pool.record({**failure, "event": "failed", "will_retry": False})
                    raise ReadDeadlineError(failure)
                metadata = result.get("ResponseMetadata", {}) if isinstance(result, dict) else {}
                pool.record(
                    {
                        **context,
                        "event": "succeeded",
                        "attempt": attempt,
                        "elapsed_seconds": round(pool.clock() - started, 6),
                        "request_id": metadata.get("RequestId"),
                    }
                )
                return result
            raise AssertionError("unreachable operator retry loop")

        return call
