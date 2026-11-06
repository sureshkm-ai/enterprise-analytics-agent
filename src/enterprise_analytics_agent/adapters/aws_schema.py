"""Governed AWS storage identifiers shared by adapters and infrastructure."""

import re
from hashlib import sha256

from enterprise_analytics_agent.snapshots import SNAPSHOT_SCHEMAS, validate_dataset_version

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,30}\Z")


def glue_table_name(dataset_version: str, table: str, *, prefix: str = "ea") -> str:
    """Deterministic closed table identifiers shared by infrastructure and adapters."""
    validate_dataset_version(dataset_version)
    if table not in SNAPSHOT_SCHEMAS or _IDENTIFIER.fullmatch(prefix) is None:
        raise ValueError("Invalid governed table or table prefix")
    return f"{prefix}_{sha256(dataset_version.encode()).hexdigest()[:16]}_{table}"
