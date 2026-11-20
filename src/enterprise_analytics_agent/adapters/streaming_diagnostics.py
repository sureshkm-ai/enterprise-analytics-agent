"""Private AWS failure evidence; never a model message or public agent response."""

import json
import re
from collections.abc import Callable

from botocore.exceptions import ClientError

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w-])(?:[\"']?)(?:"
    r"(?:aws[_-]?)?(?:access[_-]?key[_-]?id|secret[_-]?(?:access[_-]?)?key|session[_-]?token)"
    r"|authorization|credentials?|password|api[_-]?key|token|signature|signedheaders"
    r"|x-amz-(?:credential|security-token|signature)"
    r"|prompts?|questions?|messages|history|payload|headers|httpheaders|inputbody|outputbody"
    r"|system(?:[_-]?prompt)?|conversation|reasoning(?:[_-]?content)?"
    r")(?:[\"']?)\s*[:=]\s*"
)
_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/#-]{1,256}\Z")


def _redact_message(message: str) -> str:
    """Keep complete ordinary denial text while removing secret/payload assignments."""
    decoder = json.JSONDecoder()
    parts: list[str] = []
    position = 0
    while match := _SENSITIVE_ASSIGNMENT.search(message, position):
        parts.append(message[position : match.end()])
        start = match.end()
        end = len(message)
        if start < len(message) and message[start] in '{["':
            try:
                _, end = decoder.raw_decode(message, start)
            except ValueError:
                # A malformed sensitive value must not expose its remaining body.
                pass
        elif start < len(message) and message[start] == "'":
            quoted = re.match(r"'(?:\\.|[^'\\])*'", message[start:])
            if quoted:
                end = start + quoted.end()
        else:
            separator = re.search(r"[,;}\]&\r\n]", message[start:])
            if separator:
                end = start + separator.start()
        parts.append("[redacted]")
        position = end
    parts.append(message[position:])
    value = "".join(parts)
    value = _ACCESS_KEY.sub("[redacted-access-key-id]", value)
    value = _BEARER.sub("Bearer [redacted]", value)
    return _JWT.sub("[redacted-token]", value)


def report_aws_failure(
    error: BaseException,
    *,
    operation: str | None,
    number: int,
    diagnostic: Callable[[dict[str, object]], None],
) -> None:
    """Best-effort allowlisted ClientError fields, separate from SDK accounting.

    The sink is internal and request-scoped. Generic exception text, request
    arguments, headers, credentials and arbitrary SDK response fields are never
    copied. A broken diagnostic sink cannot replace the original failure.
    """
    try:
        current: BaseException | None = error
        found: ClientError | None = None
        seen: set[int] = set()
        # Publication/setup helpers deliberately wrap SDK failures. Inspect only
        # explicit causes, bounded to eight nodes; never inspect implicit context
        # or stringify a wrapper that may contain private request data.
        for _ in range(8):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            if isinstance(current, ClientError):
                found = current
                break
            current = current.__cause__
        if found is None:
            return
        if operation is None:
            supplied = getattr(found, "operation_name", None)
            operation = (
                supplied
                if isinstance(supplied, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", supplied)
                else "RuntimeSetup"
            )
        details = found.response.get("Error", {})
        metadata = found.response.get("ResponseMetadata", {})
        if not isinstance(details, dict) or not isinstance(metadata, dict):
            return
        aws_error: dict[str, object] = {}
        code, message = details.get("Code"), details.get("Message")
        request_id, status = metadata.get("RequestId"), metadata.get("HTTPStatusCode")
        if isinstance(code, str) and _IDENTIFIER.fullmatch(code):
            aws_error["Code"] = _redact_message(code)
        if isinstance(message, str):
            aws_error["Message"] = _redact_message(message)
        if isinstance(request_id, str) and _IDENTIFIER.fullmatch(request_id):
            aws_error["RequestId"] = _redact_message(request_id)
        if type(status) is int and 100 <= status <= 599:
            aws_error["HTTPStatusCode"] = status
        diagnostic({"operation": operation, "number": number, "aws_error": aws_error})
    except BaseException:
        # This optional sink must not interfere with the mandatory attempt journal,
        # original exception, cancellation, token counters or failure propagation.
        pass
