"""Workload credentials with explicit, refreshable assumption of the Athena query role."""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config

from enterprise_analytics_agent.hosting.config import RuntimeSettings

CONTROL_CONFIG = Config(
    connect_timeout=5, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 1}
)
ATHENA_CONFIG = Config(
    connect_timeout=5, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 1}
)


class Session(Protocol):
    def client(self, service_name: str, **kwargs: Any) -> Any: ...


def credential_session(**kwargs: Any) -> Session:
    # The SDK's generated per-service overloads do not express this internal proxy's
    # dynamic service-name protocol; the runtime methods are the same SDK methods.
    return cast(Session, boto3.Session(**kwargs))


class QueryRoleCredentials:
    """Refresh assumed credentials before expiry; the base SDK refreshes its workload role.

    No credentials are persisted, logged, or accepted from invocation arguments.
    Client proxies resolve the current session on every call, so a long-running
    process never retains clients signed with a stale 15-minute assumption.
    """

    def __init__(
        self,
        settings: RuntimeSettings,
        workload: Session,
        *,
        session_factory: Callable[..., Session] = credential_session,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.workload = workload
        self.session_factory = session_factory
        self.now = now
        self._expiry: datetime | None = None
        self._clients: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        sts = self.workload.client("sts", config=CONTROL_CONFIG)
        if sts.get_caller_identity()["Account"] != self.settings.account:
            raise ValueError("Workload credentials resolve to an unexpected AWS account")
        credentials = sts.assume_role(
            RoleArn=self.settings.query_role_arn,
            RoleSessionName="analytics-agentcore-query",
            DurationSeconds=900,
        )["Credentials"]
        expiry = credentials["Expiration"]
        if (
            not isinstance(expiry, datetime)
            or expiry.tzinfo is None
            or expiry <= self.now() + timedelta(seconds=120)
        ):
            raise ValueError("Assumed credentials have an invalid expiration")
        assumed = self.session_factory(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=self.settings.region,
        )
        self._clients = {
            "athena": assumed.client("athena", config=ATHENA_CONFIG),
            "s3": assumed.client("s3", config=CONTROL_CONFIG),
        }
        self._expiry = expiry

    def call(self, service: str, method: str, arguments: dict[str, object]) -> Any:
        if service not in ("athena", "s3"):
            raise ValueError("Query-role clients support only Athena and source S3")
        with self._lock:
            if self._expiry is None or self.now() + timedelta(seconds=120) >= self._expiry:
                self._refresh()
            client = self._clients[service]
        return getattr(client, method)(**arguments)

    def client(self, service: str) -> "QueryRoleClient":
        return QueryRoleClient(self, service)


class QueryRoleClient:
    """Internal proxy; only trusted adapter code chooses services and SDK methods."""

    def __init__(self, credentials: QueryRoleCredentials, service: str) -> None:
        if service not in ("athena", "s3"):
            raise ValueError("Unsupported query-role service")
        self.credentials = credentials
        self.service = service

    def __getattr__(self, method: str) -> Callable[..., Any]:
        if method.startswith("_"):
            raise AttributeError(method)

        def invoke(**kwargs: object) -> Any:
            return self.credentials.call(self.service, method, kwargs)

        return invoke


def workload_session(settings: RuntimeSettings) -> Session:
    """Use AgentCore's SDK workload credential provider; never select a local profile."""
    return cast(Session, boto3.Session(region_name=settings.region))
