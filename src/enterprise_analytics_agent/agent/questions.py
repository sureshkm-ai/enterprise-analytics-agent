"""Conservative question scope: clarify ambiguity rather than guess a metric or period."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, TimeRangeV2

_ALIASES = {
    "gross_sales": ("gross sales", "gross_sales"),
    "net_revenue": ("net revenue", "net_revenue"),
    "order_count": ("order count", "order_count", "number of orders"),
    "average_order_value": ("average order value", "average_order_value", "aov"),
    "return_rate": ("return rate", "return_rate"),
}
_REGIONS = ("North", "South", "East", "West")
_CHANNELS = ("online", "store")


@dataclass(frozen=True)
class QuestionScope:
    metric_ids: tuple[str, ...]
    periods: tuple[TimeRangeV2, ...]
    group_by: tuple[str, ...]
    filters: dict[str, tuple[str, ...]]
    metadata: bool = False
    clarification: str | None = None

    def validate_query(self, request: QueryMetricRequestV2) -> None:
        if self.metadata:
            raise ValueError("A metadata question does not authorize a metric query")
        if request.metric_id not in self.metric_ids or request.time_range not in self.periods:
            raise ValueError("Query metric or period was not explicitly requested")
        if set(request.group_by) != set(self.group_by):
            raise ValueError("Query grouping differs from the requested grouping")
        if {key: set(values) for key, values in request.dimension_filters.items()} != {
            key: set(values) for key, values in self.filters.items()
        }:
            raise ValueError("Query filters differ from the requested filters")


def _month_range(year: int, month: int) -> TimeRangeV2:
    return TimeRangeV2(
        start=date(year, month, 1),
        end=date(year + (month == 12), 1 if month == 12 else month + 1, 1),
    )


def question_scope(question: str, reference_date: date) -> QuestionScope:
    """Recognize a deliberately small, documented development question vocabulary.

    This is a fail-closed planning guard, not an LLM-supplied identity or calendar.
    The model still selects tools and builds requests, which are checked independently.
    """
    text = question.casefold()
    metrics = tuple(
        metric
        for metric, aliases in _ALIASES.items()
        if any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases)
    )
    periods: list[TimeRangeV2] = []
    explicit = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    invalid_period = False
    if explicit:
        # An ISO pair uses the public [start,end) semantic contract; do not guess
        # whether natural-language 'through'/'between' intended an inclusive end.
        if len(explicit) == 2 and ("[" in text and ")" in text or "exclusive" in text):
            try:
                periods.append(TimeRangeV2(start=explicit[0], end=explicit[1]))
            except ValueError:
                invalid_period = True
        else:
            invalid_period = True
    else:
        for month in range(1, 13):
            names = {calendar.month_name[month].casefold(), calendar.month_abbr[month].casefold()}
            for match in re.finditer(rf"\b(?:{'|'.join(names)})\s+(\d{{4}})\b", text):
                try:
                    periods.append(_month_range(int(match[1]), month))
                except ValueError:
                    invalid_period = True
        if "last month" in text:
            previous = date(reference_date.year, reference_date.month, 1) - timedelta(days=1)
            periods.append(_month_range(previous.year, previous.month))
        if "yesterday" in text:
            periods.append(
                TimeRangeV2(start=reference_date - timedelta(days=1), end=reference_date)
            )
    unique_periods = tuple(dict.fromkeys((period.start, period.end) for period in periods))
    periods = [TimeRangeV2(start=start, end=end) for start, end in unique_periods]
    regions = tuple(value for value in _REGIONS if re.search(rf"\b{value.casefold()}\b", text))
    channels = tuple(value for value in _CHANNELS if re.search(rf"\b{value}\b", text))
    filters: dict[str, tuple[str, ...]] = {}
    if regions:
        filters["region"] = regions
    if channels:
        filters["channel"] = channels
    groups = []
    comparison = bool(re.search(r"\b(compar(?:e|es|ed|ing|ison)|versus|vs)\b", text))
    unsupported_metric = bool(
        re.search(r"\b(profit|margin|conversion_rate|customer_count|tax_total)\b", text)
    )
    unsupported = any(
        match.rstrip("s") not in ("region", "channel")
        for match in re.findall(r"\b(?:by|per|across)\s+([a-z]+)\b", text)
    )
    unsupported = unsupported or bool(
        re.search(r"\b(daily|weekly|hourly|yearly|quarterly)\b", text)
    )
    allowed_values = {"region": {value.casefold() for value in _REGIONS}, "channel": set(_CHANNELS)}
    for dimension, value in re.findall(
        r"\b(region|channel|product|customer|category)\s*(?:=|:|\bis\b)\s*['\"]?([a-z_-]+)", text
    ):
        if dimension not in allowed_values or value not in allowed_values[dimension]:
            unsupported = True
    month_names = {value.casefold() for value in (*calendar.month_name, *calendar.month_abbr)}
    for value in re.findall(r"\b(?:for|in)\s+([a-z_-]+)\b", text):
        if value not in {
            *month_names,
            *(name.casefold() for name in _REGIONS),
            *_CHANNELS,
            "last",
            "yesterday",
            "all",
            "each",
            "both",
            *metrics,
        }:
            unsupported = True
    for dimension in ("region", "channel"):
        if re.search(rf"\b(by|per|each|across)\s+{dimension}s?\b", text):
            groups.append(dimension)
    if groups and re.search(
        r"\bregions?\s*(?:and|,)\s*channels?\b|\bchannels?\s*(?:and|,)\s*regions?\b", text
    ):
        groups = ["region", "channel"]
    if comparison and len(regions) > 1 and "region" not in groups:
        groups.append("region")
    if comparison and len(channels) > 1 and "channel" not in groups:
        groups.append("channel")
    discovery = bool(
        re.search(r"\bmetrics\b", text)
        and re.search(r"\b(available|supported|discover|list|which|what)\b", text)
    )
    metadata = discovery or (
        not periods
        and bool(
            re.search(
                r"\b(define|definition|describe|calculated|dimensions|regions|channels)\b", text
            )
        )
    )
    clarification = None
    if not metrics and not discovery:
        clarification = (
            "Please choose a governed metric: gross sales, net revenue, order count, "
            "average order value, or return rate."
        )
    elif unsupported_metric:
        clarification = (
            "The request includes an unsupported metric. Please choose only gross sales, "
            "net revenue, order count, average order value, or return rate."
        )
    elif not metadata and (not periods or invalid_period):
        clarification = (
            "Please specify a month and year, yesterday, last month, or an explicit "
            "inclusive-start/exclusive-end date range such as [YYYY-MM-DD, YYYY-MM-DD)."
        )
    elif not metadata and unsupported:
        clarification = (
            "Please clarify the grouping or filter. Supported dimensions are region and channel, "
            "with the configured retail values; unsupported dimensions or values are not ignored."
        )
    elif (
        not metadata
        and len(metrics) > 1
        and len(periods) > 1
        and not re.search(
            r"\b(?:each|every)\s+metric\b.*\b(?:each|every)\s+(?:period|month)\b|"
            r"\bboth\s+metrics\b.*\bboth\s+(?:periods|months)\b",
            text,
        )
    ):
        clarification = (
            "Please clarify which metrics belong to which periods, "
            "or request each metric in each period."
        )
    elif not metadata and len(periods) > 1 and not comparison and "each period" not in text:
        clarification = (
            "Please clarify whether these months are separate comparison periods "
            "or one continuous range."
        )
    elif re.search(
        r"\b(change|growth|increase|decrease|difference|exclud(?:e|es|ed|ing)|except|without|"
        r"not|outside|other\s+than|rather\s+than|minus|subtract)\b|\bdon't\b",
        text,
    ):
        clarification = (
            "Please clarify the comparison or filter. This agent can show governed results "
            "side by side; it does not invent change metrics or exclusion filters."
        )
    elif comparison and len(periods) < 2 and not groups and len(metrics) < 2:
        clarification = "Please specify the periods, metrics, or dimension groups to compare."
    return QuestionScope(metrics, tuple(periods), tuple(groups), filters, metadata, clarification)
