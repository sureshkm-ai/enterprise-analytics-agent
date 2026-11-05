"""Stable application exceptions independent of backend client exceptions."""


class SemanticError(Exception):
    """Base error for invalid semantic operations."""


class UnknownMetricError(SemanticError):
    """The requested metric is not in the governed catalog."""


class InvalidDimensionError(SemanticError):
    """A grouping or filter dimension is not allowed by the metric."""


class AuthorizationError(SemanticError):
    """The trusted context does not permit this operation."""


class DataValidationError(SemanticError):
    """A local snapshot is missing, malformed, or contains conflicting records."""


class MissingMetricDataError(DataValidationError):
    """A metric requires an optional source that the loaded snapshot does not contain."""


class UnsupportedMetricVersionError(SemanticError):
    """The metric requires a newer semantic contract version."""
