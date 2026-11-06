"""Synthesize the reviewed CDK configuration without account lookups or SDK clients."""

import argparse
from pathlib import Path

from aws_cdk import App, Environment

from infrastructure.cdk.config import DeploymentConfig
from infrastructure.cdk.stack import AnalyticsDataStack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--outdir", type=str, help="Cloud assembly directory (otherwise honors CDK_OUTDIR)"
    )
    args = parser.parse_args()
    config = DeploymentConfig.model_validate_json(args.config.read_text())
    app = App(outdir=args.outdir, analytics_reporting=False)
    AnalyticsDataStack(
        app,
        f"{config.resource_prefix}-data-layer",
        config=config,
        env=Environment(account=config.account, region=config.region),
    )
    app.synth()


if __name__ == "__main__":
    main()
