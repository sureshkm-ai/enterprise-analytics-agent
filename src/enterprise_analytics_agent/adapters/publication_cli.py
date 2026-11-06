"""Operator-only publication command, run only after development deployment approval."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from enterprise_analytics_agent.adapters.aws_runtime import (
    SDK_CONFIG,
    load_runtime_config,
    session_for_role,
)
from enterprise_analytics_agent.adapters.s3_publication import (
    GlueClient,
    PublicationConfig,
    S3Client,
    publish_snapshot,
)
from enterprise_analytics_agent.errors import SemanticError
from enterprise_analytics_agent.snapshots import prepare_snapshot


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish an immutable, validated development snapshot."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(args.config)
        target = config.target(args.dataset_version)
        # All local validation and version/returns checks precede even SDK session creation.
        with prepare_snapshot(args.source_dir, args.dataset_version, seed=args.seed) as prepared:
            if ("returns" in prepared.manifest.tables) != target.include_returns:
                raise ValueError("Returns inventory does not match the reviewed deployment version")
            session = session_for_role(config, "loader")
            result = publish_snapshot(
                prepared,
                s3=cast(S3Client, session.client("s3", config=SDK_CONFIG)),
                glue=cast(GlueClient, session.client("glue", config=SDK_CONFIG)),
                config=PublicationConfig(
                    bucket=config.source_bucket,
                    database=config.database_name,
                    expected_account_id=config.account,
                    table_prefix=config.table_prefix,
                ),
            )
    except (SemanticError, BotoCoreError, ClientError, ValidationError, ValueError, OSError) as exc:
        print(f"analytics-publish: {exc}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0
