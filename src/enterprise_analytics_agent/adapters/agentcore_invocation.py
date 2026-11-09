"""Operator-only AWS transport; never imported to replay an offline response.

SDK reference: https://docs.aws.amazon.com/boto3/latest/reference/services/
bedrock-agentcore/client/invoke_agent_runtime.html and botocore Config retries.
"""

from typing import Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from enterprise_analytics_agent.retail_evaluation.client import (
    ResponseBody,
    RuntimeInvoker,
    RuntimeReply,
)
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget


class RuntimeClient(Protocol):
    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]: ...


class _ResponseBody:
    def __init__(self, body: ResponseBody) -> None:
        self.body = body

    def read(self) -> bytes:
        try:
            return self.body.read()
        except ReadTimeoutError as exc:
            raise TimeoutError("AgentCore response body timed out") from exc

    def close(self) -> None:
        self.body.close()


def create_runtime_invoker(target: RetailTarget) -> RuntimeInvoker:
    """Create the sole approved profile/session and verify account before dispatch.

    total_max_attempts includes the first HTTP attempt: one disables hidden SDK
    retries, so one persistent reservation always covers at most one invocation.
    """
    try:
        return _create_runtime_invoker(target)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("AWS operator transport configuration failed") from exc


def _create_runtime_invoker(target: RetailTarget) -> RuntimeInvoker:
    session = boto3.Session(profile_name=target.profile, region_name=target.region)
    config = Config(
        connect_timeout=5,
        read_timeout=150,
        retries={"total_max_attempts": 1, "mode": "standard"},
    )
    identity = session.client("sts", config=config).get_caller_identity()
    if identity["Account"] != target.account:
        raise ValueError("AWS identity does not match the approved account")
    client = cast(RuntimeClient, session.client("bedrock-agentcore", config=config))

    def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
        try:
            result = client.invoke_agent_runtime(
                agentRuntimeArn=target.runtime_arn,
                runtimeSessionId=session_id,
                qualifier=target.qualifier,
                contentType="application/json",
                accept="application/json",
                payload=payload,
            )
        except (ConnectTimeoutError, ReadTimeoutError) as exc:
            raise TimeoutError("AgentCore invocation timed out") from exc
        body = cast(ResponseBody, result["response"])
        status = result.get("statusCode")
        if type(status) is int and status != 200:
            body.close()
            raise RuntimeError("AgentCore invocation returned an unsuccessful HTTP status")
        # AWS returns traceId; do not retain sessionEndpointUrl or signed headers.
        trace_id = result.get("traceId")
        return RuntimeReply(_ResponseBody(body), trace_id if isinstance(trace_id, str) else None)

    return invoke
