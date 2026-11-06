"""Private Athena lifecycle and exact result decoding; no public semantic contracts."""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from uuid import uuid4

from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from enterprise_analytics_agent.errors import DataValidationError, SemanticError


class AthenaClient(Protocol):
    """The four SDK calls used by this adapter; fakes never need credentials."""

    def start_query_execution(self, **kwargs: object) -> dict[str, object]: ...

    def get_query_execution(self, **kwargs: object) -> dict[str, object]: ...

    def get_query_results(self, **kwargs: object) -> dict[str, object]: ...

    def stop_query_execution(self, **kwargs: object) -> dict[str, object]: ...


class AthenaExecutionError(SemanticError):
    """A query/API failed; operational details stay in internal diagnostics."""


class AthenaTimeoutError(AthenaExecutionError):
    """The total deadline expired; an accepted running query was cancelled."""


@dataclass(frozen=True)
class AthenaDiagnostic:
    query_id: str | None
    operation: str
    metric_id: str
    metric_version: str
    dataset_version: str
    state: str
    scanned_bytes: int | None = None
    engine_time_ms: int | None = None
    queue_time_ms: int | None = None
    total_time_ms: int | None = None


_TRANSIENT_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "TooManyRequestsException",
        "InternalServerException",
        "InternalServerError",
        "ServiceUnavailable",
        "ServiceUnavailableException",
        "RequestTimeout",
        "RequestTimeoutException",
    }
)
_TRANSIENT_CONNECTION_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
_INTEGER = re.compile(r"[+-]?\d+\Z", flags=re.ASCII)


def encode_parameter(value: object) -> str:
    """Athena execution parameters are SQL literals, not raw string arguments."""
    if type(value) is date:
        return f"CAST('{value.isoformat()}' AS DATE)"
    if isinstance(value, str):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise DataValidationError("Control characters are not valid query parameter values")
        return "'" + value.replace("'", "''") + "'"
    if type(value) is int:
        return str(value)
    raise DataValidationError("Only validated strings, dates and integer parameters are supported")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DataValidationError(f"Malformed Athena {label}")
    return cast(dict[str, object], value)


def _items(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise DataValidationError(f"Malformed Athena {label}")
    return cast(list[object], value)


def _optional_integer(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _cell(value: object, kind: str) -> object:
    cell = _object(value, "result cell")
    if "VarCharValue" not in cell:
        return None
    text = cell["VarCharValue"]
    if not isinstance(text, str):
        raise DataValidationError("Malformed Athena result value")
    base_type = kind.partition("(")[0].lower()
    if base_type in ("varchar", "char", "string"):
        return text
    if base_type in ("tinyint", "smallint", "integer", "int", "bigint"):
        if not _INTEGER.fullmatch(text):
            raise DataValidationError("Athena returned an invalid integer")
        return int(text)
    if base_type == "decimal":
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise DataValidationError("Athena returned an invalid decimal") from exc
        if not result.is_finite():
            raise DataValidationError("Athena returned a non-finite decimal")
        return result
    raise DataValidationError(f"Unsupported Athena result type: {kind}")


class AthenaExecutor:
    """An internal bounded executor used exclusively with governed generated SQL."""

    def __init__(
        self,
        client: AthenaClient,
        *,
        database: str,
        workgroup: str,
        output_location: str,
        expected_bucket_owner: str,
        timeout_seconds: float,
        poll_seconds: float,
        max_attempts: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.database = database
        self.workgroup = workgroup
        self.output_location = output_location
        self.expected_bucket_owner = expected_bucket_owner
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.max_attempts = max_attempts
        self.clock = clock
        self.sleep = sleep
        self.diagnostics: list[AthenaDiagnostic] = []

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise AthenaTimeoutError("Athena query exceeded its configured total deadline")
        return remaining

    def _pause(self, delay: float, deadline: float) -> None:
        self.sleep(min(delay, self._remaining(deadline)))
        self._remaining(deadline)

    def _call(
        self,
        function: Callable[..., dict[str, object]],
        deadline: float,
        **kwargs: object,
    ) -> dict[str, object]:
        for attempt in range(self.max_attempts):
            self._remaining(deadline)
            try:
                return function(**kwargs)
            except (*_TRANSIENT_CONNECTION_ERRORS, ClientError) as exc:
                if isinstance(exc, ClientError):
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code not in _TRANSIENT_CODES:
                        raise AthenaExecutionError("Athena API request failed") from exc
                if attempt + 1 >= self.max_attempts:
                    raise AthenaExecutionError(
                        "Athena transient API retries were exhausted"
                    ) from exc
                self._pause(min(0.25 * 2**attempt, 2.0), deadline)
        raise AssertionError("Unreachable retry state")

    def _record(
        self,
        query_id: str | None,
        operation: str,
        metric_id: str,
        metric_version: str,
        dataset_version: str,
        state: str,
        execution: dict[str, object],
    ) -> None:
        statistics = _object(execution.get("Statistics", {}), "query statistics")
        self.diagnostics.append(
            AthenaDiagnostic(
                query_id=query_id,
                operation=operation,
                metric_id=metric_id,
                metric_version=metric_version,
                dataset_version=dataset_version,
                state=state,
                scanned_bytes=_optional_integer(statistics.get("DataScannedInBytes")),
                engine_time_ms=_optional_integer(statistics.get("EngineExecutionTimeInMillis")),
                queue_time_ms=_optional_integer(statistics.get("QueryQueueTimeInMillis")),
                total_time_ms=_optional_integer(statistics.get("TotalExecutionTimeInMillis")),
            )
        )

    def execute(
        self,
        sql: str,
        parameters: list[object],
        *,
        operation: str,
        metric_id: str,
        metric_version: str,
        dataset_version: str,
    ) -> list[tuple[object, ...]]:
        deadline = self.clock() + self.timeout_seconds
        encoded = [encode_parameter(value) for value in parameters]
        for execution_attempt in range(self.max_attempts):
            query_id: str | None = None
            execution: dict[str, object] = {}
            state = "SUBMISSION_FAILED"
            try:
                # Stable within API retries; a new token only for an explicitly retryable
                # terminal execution, never after an uncertain submission response.
                submitted = self._call(
                    self.client.start_query_execution,
                    deadline,
                    QueryString=sql,
                    ClientRequestToken=uuid4().hex,
                    QueryExecutionContext={"Database": self.database, "Catalog": "AwsDataCatalog"},
                    WorkGroup=self.workgroup,
                    ResultConfiguration={
                        "OutputLocation": self.output_location,
                        "ExpectedBucketOwner": self.expected_bucket_owner,
                        "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
                    },
                    ExecutionParameters=encoded,
                    ResultReuseConfiguration={"ResultReuseByAgeConfiguration": {"Enabled": False}},
                )
                value = submitted.get("QueryExecutionId")
                if not isinstance(value, str) or not value:
                    raise DataValidationError("Athena did not return a query execution identifier")
                query_id = value
                while True:
                    result = self._call(
                        self.client.get_query_execution, deadline, QueryExecutionId=query_id
                    )
                    execution = _object(result.get("QueryExecution"), "query execution")
                    status = _object(execution.get("Status"), "query status")
                    status_state = status.get("State")
                    if status_state not in (
                        "QUEUED",
                        "RUNNING",
                        "SUCCEEDED",
                        "FAILED",
                        "CANCELLED",
                    ):
                        raise DataValidationError("Athena returned an unknown query status")
                    state = str(status_state)
                    if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                        break
                    self._pause(self.poll_seconds, deadline)
                if state == "FAILED":
                    error = _object(status.get("AthenaError", {}), "query error")
                    if error.get("Retryable") is True and execution_attempt + 1 < self.max_attempts:
                        self._pause(min(0.25 * 2**execution_attempt, 2.0), deadline)
                        continue
                    raise AthenaExecutionError("Athena query failed; inspect internal diagnostics")
                if state == "CANCELLED":
                    raise AthenaExecutionError("Athena query was cancelled")
                state = "RESULTS_FAILED"
                rows = self._results(query_id, deadline)
                state = "SUCCEEDED"
                return rows
            except AthenaTimeoutError:
                state = "TIMED_OUT"
                if query_id is not None:
                    # A separate bounded cancellation attempt is necessary after the
                    # execution deadline expires. Socket timeouts are set by the factory.
                    try:
                        self._call(
                            self.client.stop_query_execution,
                            self.clock() + min(self.timeout_seconds, 5.0),
                            QueryExecutionId=query_id,
                        )
                    except (AthenaExecutionError, DataValidationError):
                        state = "TIMED_OUT_CANCELLATION_FAILED"
                raise
            finally:
                self._record(
                    query_id,
                    operation,
                    metric_id,
                    metric_version,
                    dataset_version,
                    state,
                    execution,
                )
        raise AthenaExecutionError("Athena execution retries were exhausted")

    def _results(self, query_id: str, deadline: float) -> list[tuple[object, ...]]:
        rows: list[tuple[object, ...]] = []
        columns: list[dict[str, object]] | None = None
        token: str | None = None
        seen_tokens: set[str] = set()
        first_page = True
        while True:
            arguments: dict[str, object] = {"QueryExecutionId": query_id, "MaxResults": 1000}
            if token is not None:
                arguments["NextToken"] = token
            page = self._call(self.client.get_query_results, deadline, **arguments)
            self._remaining(deadline)
            result_set = _object(page.get("ResultSet"), "result set")
            metadata = _object(result_set.get("ResultSetMetadata"), "result metadata")
            page_columns = [
                _object(column, "column metadata")
                for column in _items(metadata.get("ColumnInfo"), "column metadata")
            ]
            if not page_columns or any(
                not isinstance(column.get("Name"), str) or not isinstance(column.get("Type"), str)
                for column in page_columns
            ):
                raise DataValidationError("Athena returned incomplete result metadata")
            if columns is None:
                columns = page_columns
            elif columns != page_columns:
                raise DataValidationError("Athena result metadata changed between pages")
            page_rows = _items(result_set.get("Rows", []), "result rows")
            if first_page:
                # SELECT results have one header row on the first page only. Validate
                # it instead of dropping a data row based on its values on every page.
                if not page_rows:
                    raise DataValidationError("Athena SELECT results did not include a header")
                header = _object(page_rows[0], "result header")
                values = _items(header.get("Data"), "result header cells")
                expected = [column["Name"] for column in columns]
                actual = [_object(cell, "header cell").get("VarCharValue") for cell in values]
                if actual != expected:
                    raise DataValidationError("Athena result header did not match metadata")
                page_rows = page_rows[1:]
                first_page = False
            for raw_row in page_rows:
                cells = _items(_object(raw_row, "result row").get("Data"), "result row cells")
                if len(cells) != len(columns):
                    raise DataValidationError("Athena returned an invalid result column count")
                rows.append(
                    tuple(
                        _cell(cell, str(column["Type"]))
                        for cell, column in zip(cells, columns, strict=True)
                    )
                )
            next_token = page.get("NextToken")
            if next_token is None:
                return rows
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise DataValidationError("Athena returned an invalid or repeated page token")
            seen_tokens.add(next_token)
            token = next_token
