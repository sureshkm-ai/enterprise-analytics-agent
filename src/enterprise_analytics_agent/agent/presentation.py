"""Readable answers derived only from the validated semantic response.

The wire contract and its exact Decimal values remain unchanged. Both the local
and hosted streaming adapters use this same renderer; the model copies this
verified text and cannot add calculations or unsupported conclusions.
"""

import re
from datetime import date, timedelta

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.catalog import METRICS
from enterprise_analytics_agent.contracts_v2 import QueryMetricResponseV2


def _literal(value: str) -> str:
    """Escape data before placing it in the small supported Markdown vocabulary."""
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", value.replace("\n", " ").replace("\r", " "))


def _date(value: date) -> str:
    return f"{value:%B} {value.day}, {value.year}"


def _period(result: QueryMetricResponseV2) -> str:
    start, last = result.time_range.start, result.time_range.end - timedelta(days=1)
    return _date(start) if start == last else f"{_date(start)} to {_date(last)}"


def _value(value: object, result: QueryMetricResponseV2) -> str:
    if value is None:
        return "Not defined (zero denominator)"
    suffix = (
        f" {result.currency}"
        if result.unit == "currency"
        else " (ratio)"
        if result.unit == "ratio"
        else ""
    )
    return _literal(f"{value}{suffix}")


def readable_answer(response: AgentResponse) -> str:
    """Format exact results, including empty/null cases, without changing their grain."""
    if response.status != "answer" or not response.results:
        # Clarifications and errors are authored by the governed agent. Treat
        # them as plain text, never provider-authored HTML or Markdown.
        return _literal(response.answer)
    names = {metric.metric_id: metric.display_name for metric in METRICS}
    sections = []
    for result in response.results:
        name = _literal(names.get(result.metric_id, result.metric_id.replace("_", " ").title()))
        period = _period(result)
        if not result.rows:
            body = f"No eligible results for **{period}** in the authorized scope."
        elif not result.group_by and len(result.rows) == 1:
            body = f"{name}: **{_value(result.rows[0].value, result)}** for **{period}**."
        else:
            labels = [_literal(key.replace("_", " ").title()) for key in result.group_by]
            rows = ["| " + " | ".join([*labels, name]) + " |"]
            rows.append("| " + " | ".join("---" for _ in range(len(labels) + 1)) + " |")
            for row in result.rows:
                values = [_literal(str(row.dimensions.get(key, "—"))) for key in result.group_by]
                rows.append("| " + " | ".join([*values, _value(row.value, result)]) + " |")
            body = f"For **{period}**:\n\n" + "\n".join(rows)
        sections.append(
            f"### {name}\n\n{body}" if len(response.results) > 1 or result.group_by else body
        )
    return "\n\n".join(sections)
