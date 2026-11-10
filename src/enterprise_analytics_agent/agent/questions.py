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
_QUESTION_WORDS = frozenset(
    "show please me the what which is are was were how much many did make made get give tell find "
    "can could would you i want need like total totals for in from to by per across each every "
    "both all of and or with versus vs compare compares compared comparing comparison period "
    "periods month months region regions channel channels inclusive start exclusive end date "
    "range between list available supported discover metric metrics describe define definition "
    "calculated dimensions values".split()
)


def _has_unrepresented_words(text: str) -> bool:
    """Account for the whole question, rather than only extracting known fragments.

    Remove supported semantic phrases, then allow only ordinary question scaffolding.
    An unknown measure, dimension, date refinement or other clause must clarify;
    keeping a recognized metric/month is insufficient evidence for a complete plan.
    """
    phrases = [alias for aliases in _ALIASES.values() for alias in aliases]
    phrases.extend((*_REGIONS, *_CHANNELS, "last month", "yesterday"))
    remaining = re.sub(
        r"\b(?:" + "|".join(re.escape(value.casefold()) for value in phrases) + r")\b",
        " ",
        text,
    )
    remaining = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", remaining)
    months = {name.casefold() for name in (*calendar.month_name, *calendar.month_abbr) if name}
    remaining = re.sub(r"\b(?:" + "|".join(months) + r")\s+\d{4}\b", " ", remaining)
    remaining = re.sub(r"\b(?:grouped|grouping|broken\s+down)\s+(?=by\b)", " ", remaining)
    return any(word not in _QUESTION_WORDS for word in re.findall(r"\w+", remaining))


def _has_cross_dimension_or(text: str) -> bool:
    # Explicit same-dimension alternatives can be conjoined with another filter.
    # Unparenthesized mixed AND/OR is ambiguous and must not become an implicit AND.
    for dimension, values in (("region", _REGIONS), ("channel", _CHANNELS)):
        value = (
            rf"(?:{dimension}\s*(?:=|:|is)?\s*)?"
            rf"(?:{'|'.join(item.casefold() for item in values)})\b"
        )
        text = re.sub(rf"\(\s*{value}(?:\s+or\s+{value})+\s*\)", " ", text)
    return bool(re.search(r"\bor\b", text))


def _grouping_clauses(text: str) -> tuple[list[str], bool]:
    """Validate every member of a coordinated grouping, including repeated prefixes."""
    prefix = r"(?:by|per|across|each(?=\s+(?:regions?|channels?)\b))"
    member = rf"(?:{prefix}\s+)?[a-z_]+"
    separator = r"(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)"
    groups: set[str] = set()
    unsupported = False
    for match in re.finditer(rf"\b{prefix}\s+({member}(?:{separator}{member})*)", text):
        words = re.findall(r"[a-z_]+", match[1])
        if "or" in words:
            unsupported = True
        for word in words:
            if word in {"and", "or", "by", "per", "across", "each"}:
                continue
            dimension = word.removesuffix("s")
            if dimension not in {"region", "channel"}:
                unsupported = True
            else:
                groups.add(dimension)
    return [dimension for dimension in ("region", "channel") if dimension in groups], unsupported


@dataclass(frozen=True)
class QuestionScope:
    metric_ids: tuple[str, ...]
    periods: tuple[TimeRangeV2, ...]
    group_by: tuple[str, ...]
    filters: dict[str, tuple[str, ...]]
    metadata: bool = False
    clarification: str | None = None

    def validate_query(self, request: QueryMetricRequestV2) -> None:
        if self.clarification:
            raise ValueError("An unresolved question cannot authorize a partial semantic plan")
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
    Model-selected requests are checked independently. A complete numeric scope also
    supplies a bounded server plan if the model ends without issuing a query.
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
    groups, unsupported = _grouping_clauses(text)
    comparison = bool(re.search(r"\b(compar(?:e|es|ed|ing|ison)|versus|vs)\b", text))
    unsupported_metric = bool(
        re.search(r"\b(profit|margin|conversion_rate|customer_count|tax_total)\b", text)
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
    elif regions and channels and _has_cross_dimension_or(text):
        clarification = (
            "Please clarify the filter alternatives. The semantic contract supports OR within "
            "one dimension and AND across dimensions; it cannot combine region OR channel."
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
    elif _has_unrepresented_words(text):
        clarification = (
            "Please clarify the complete request. A metric, grouping, filter or date clause "
            "is unsupported and cannot be dropped. Use governed metric names, region/channel "
            "dimensions and a named month or explicit [YYYY-MM-DD, YYYY-MM-DD) period."
        )
    return QuestionScope(metrics, tuple(periods), tuple(groups), filters, metadata, clarification)
