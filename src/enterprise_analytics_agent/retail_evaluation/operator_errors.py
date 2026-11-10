"""Provider-independent, payload-free operator failure evidence."""

import traceback
from pathlib import Path


def error_record(exc: BaseException, phase: str) -> dict[str, object]:
    """Keep causes and code locations without credentials, locals or exception text."""
    causes: list[dict[str, object]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        entry: dict[str, object] = {"error_type": type(current).__name__}
        diagnostic = getattr(current, "diagnostic", None)
        if isinstance(diagnostic, dict):
            entry["operation"] = diagnostic
        entry["frames"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(current.__traceback__)
        ]
        causes.append(entry)
        current = current.__cause__ or current.__context__
    return {"phase": phase, "causes": causes}
