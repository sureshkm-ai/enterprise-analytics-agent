"""Fixed Bedrock Runtime Chat Completions for Kimi K3 and Nemotron Super.

Reuse the tested sequential-tool/SSE normalization, signed with AWS credentials
for Bedrock, not Mantle or a direct provider. Reasoning is explicitly disabled in
both planning and presentation; Kimi's default max effort and Converse replay
limitation are unsuitable for the bounded analytics loop.
"""

import json
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, cast

from botocore.exceptions import ClientError

from enterprise_analytics_agent.adapters.bedrock_mantle import (
    BedrockMantleClient,
    HttpSender,
    MantleError,
    _ClosingStream,
)
from enterprise_analytics_agent.adapters.bedrock_model_catalog import get_model


class RuntimeChatError(ValueError):
    """Private service diagnostics; never rendered as an analytics answer."""

    def __init__(
        self, error: MantleError, model_id: str, *, extra: dict[str, object] | None = None
    ) -> None:
        self.diagnostic: dict[str, object] = {
            **error.diagnostic,
            "service": "bedrock-runtime",
            "operation": "ChatCompletions",
            "endpoint_host": "bedrock-runtime.us-west-2.amazonaws.com",
            "model_id": model_id,
            **(extra or {}),
        }
        super().__init__("Bedrock Runtime Chat Completions failed: " + error.code)


class BedrockRuntimeChatClient(BedrockMantleClient):
    """Server-selected model only; one signed request per call, never a retry."""

    endpoint = "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1/chat/completions"
    signing_service = "bedrock"
    read_timeout_seconds = 90.0

    def __init__(
        self,
        *,
        model_key: str,
        session: Any,
        transport: HttpSender | None = None,
        timeout_seconds: float = 90,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        model = get_model(model_key)
        if model.transport != "runtime_chat":
            raise ValueError("This model is not configured for Bedrock Runtime Chat Completions.")
        self.model_id = model.model_id
        # A cross-Region response may name its concrete foundation model.
        self.response_model_ids = tuple(dict.fromkeys((model.model_id, *model.model_resource_ids)))
        super().__init__(
            session=session, transport=transport, timeout_seconds=timeout_seconds, clock=clock
        )

    def _request_payload(self, kwargs: Mapping[str, object], *, stream: bool) -> dict[str, object]:
        payload = super()._request_payload(kwargs, stream=stream)
        payload["reasoning_effort"] = "none"
        return payload

    def _http_error(self, response: Any, deadline: float) -> Exception:
        details: dict[str, Any] = {"Code": "HTTPError", "Message": "Bedrock chat request failed."}
        metadata: dict[str, Any] = {"HTTPStatusCode": response.status_code}
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        if headers.get("x-amzn-requestid"):
            metadata["RequestId"] = headers["x-amzn-requestid"]
        if headers.get("x-amzn-errortype"):
            details["Code"] = headers["x-amzn-errortype"].split(":", 1)[0]
        try:
            body = json.loads(b"".join(self._chunks(response, deadline)))
            error = body.get("error", body) if isinstance(body, dict) else {}
            if isinstance(error, dict):
                for source, target in (("message", "Message"), ("code", "Code")):
                    if isinstance(error.get(source), str):
                        details[target] = error[source]
        except (ValueError, TypeError):
            pass
        # The shared diagnostic sink redacts ClientError fields before retention.
        return ClientError(
            cast(Any, {"Error": details, "ResponseMetadata": metadata}), "ChatCompletions"
        )

    def converse(self, **kwargs: object) -> dict[str, object]:
        try:
            return super().converse(**kwargs)
        except MantleError as exc:
            raise RuntimeChatError(exc, self.model_id) from None

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        try:
            response = super().converse_stream(**kwargs)
        except MantleError as exc:
            raise RuntimeChatError(exc, self.model_id) from None
        upstream = cast(_ClosingStream, response["stream"])

        def events() -> Iterator[dict[str, object]]:
            try:
                yield from upstream
            except MantleError as exc:
                raise RuntimeChatError(exc, self.model_id) from None
            finally:
                upstream.close()

        return {"stream": _ClosingStream(events(), upstream.close)}
