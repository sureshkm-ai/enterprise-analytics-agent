"""Load version-controlled questions and independently frozen literal expectations."""

import hashlib
from pathlib import Path

from enterprise_analytics_agent.retail_evaluation.models import RetailGolden, RetailSuite


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_suite(path: Path) -> RetailSuite:
    suite = RetailSuite.model_validate_json(path.read_bytes())
    expected = [f"Q{index:02d}" for index in range(1, 35)] + ["S01A", "S01B"]
    if [case.id for case in suite.cases] != expected:
        raise ValueError("retail suite must contain reviewed Q01-Q34 followed by S01A/S01B")
    return suite


def load_goldens(path: Path, suite: RetailSuite) -> RetailGolden:
    if not path.is_file():
        raise ValueError(
            "retail expectations are unfrozen: verified canonical provenance is required"
        )
    golden = RetailGolden.model_validate_json(path.read_bytes())
    if {case.case_id for case in golden.cases} != {case.id for case in suite.cases}:
        raise ValueError("goldens must cover every reviewed case, including safe empty outcomes")
    return golden


def verify_frozen_inputs(
    questions: Path,
    expected: Path,
    provenance: Path,
    golden: RetailGolden,
) -> dict[str, object]:
    """Bind reviewed literals to the verified canonical snapshot and current audit inputs."""
    import json

    source = json.loads(provenance.read_bytes())
    if not isinstance(source, dict) or source.get("verified") is not True:
        raise ValueError("canonical input provenance is not verified; expectations remain unfrozen")
    if (
        source.get("profile") != "analytics-dev"
        or source.get("account") != "453711491609"
        or source.get("region") != "us-west-2"
        or source.get("dataset_version") != "retail-v1"
    ):
        raise ValueError("canonical provenance differs from the approved data scope")
    manifest = source.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("sha256") != golden.manifest_sha256:
        raise ValueError("expected results refer to another canonical manifest")
    checks = {
        "questions_sha256": questions,
        "expected_results_sha256": expected,
        "oracle_source_sha256": Path(__file__).with_name("oracle.py"),
        "contributions_sha256": expected.with_name("contributions.csv"),
    }
    for name, path in checks.items():
        if source.get(name) != file_sha256(path):
            raise ValueError(f"frozen evidence changed: {name}")
    return {
        "oracle_provenance_sha256": file_sha256(provenance),
        **{name: source[name] for name in checks},
    }
