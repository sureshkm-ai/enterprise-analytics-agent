"""Scoped SDK guard for the explicitly approved complete live-verification operator.

This adapter creates no client/session. It intercepts SDK dispatch only while the
operator holds its context, restoring the original method even on interruption.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from botocore.client import BaseClient

from enterprise_analytics_agent.adapters.operator_reads import _failure, _transient
from enterprise_analytics_agent.retail_evaluation.full_live import FullLiveBudgetError

if TYPE_CHECKING:
    from enterprise_analytics_agent.retail_evaluation.full_live import FullLiveBudget, FullLivePhase

_SDK_GUARD = threading.Lock()
_OPERATOR_READS = {
    "sts": {"GetCallerIdentity", "AssumeRole"},
    "s3": {"GetObject", "HeadObject", "ListObjectsV2"},
    "athena": {"GetWorkGroup", "GetQueryExecution", "GetQueryResults", "StopQueryExecution"},
    "glue": {"GetTable"},
    "cloudformation": {"DescribeStacks", "GetTemplate"},
    "bedrock-agentcore-control": {
        "GetAgentRuntime",
        "GetAgentRuntimeEndpoint",
        "GetResourcePolicy",
    },
    "logs": {"DescribeLogGroups"},
    "sso": {"GetRoleCredentials"},
    "sso-oidc": {"CreateToken"},
}


@contextmanager
def counted_full_live_sdk(budget: "FullLiveBudget", phase: "FullLivePhase") -> Iterator[None]:
    """Count dispatches; profile/STS proof is the enclosing operator's responsibility."""
    if phase not in {"athena_parity", "agent_parity", "retail", "restoration_smoke"}:
        raise FullLiveBudgetError("Invalid full-suite phase")
    if not _SDK_GUARD.acquire(blocking=False):
        raise FullLiveBudgetError("A full-suite SDK guard is already active")
    sdk: Any = BaseClient
    original = sdk._make_api_call
    owner = threading.get_ident()

    def guarded(client: Any, operation: str, parameters: dict[str, Any]) -> Any:
        service = client.meta.service_model.service_name
        billable = (service, operation) in {
            ("bedrock-agentcore", "InvokeAgentRuntime"),
            ("athena", "StartQueryExecution"),
        }
        if service == "bedrock-runtime":
            raise FullLiveBudgetError("Direct model calls are not in this full-suite scope")
        if billable:
            if threading.get_ident() != owner:
                raise FullLiveBudgetError("Billable work must stay in the owning operator thread")
            if client.meta.region_name != budget.review.region:
                raise FullLiveBudgetError("SDK client region differs from the reviewed region")
            if client.meta.config.retries.get("total_max_attempts") != 1:
                raise FullLiveBudgetError("Billable SDK retries must be disabled")
            return budget.call(
                phase,
                service,
                operation,
                parameters,
                lambda: original(client, operation, parameters),
                retryable_failure=_transient,
                failure_detail=_failure,
            )
        if operation not in _OPERATOR_READS.get(service, set()):
            raise FullLiveBudgetError("SDK operation is outside the reviewed test/read scope")
        if (
            service == "sts"
            and operation == "AssumeRole"
            and parameters.get("RoleArn")
            != "arn:aws:iam::453711491609:role/enterprise-analytics-dev-query-executor"
        ):
            raise FullLiveBudgetError("Only the existing query role may be assumed")
        return original(client, operation, parameters)

    sdk._make_api_call = guarded
    try:
        yield
    finally:
        sdk._make_api_call = original
        _SDK_GUARD.release()
