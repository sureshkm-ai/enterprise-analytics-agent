"""Offline synthesis of explicit AgentCore foundation/runtime deployment phases."""

import argparse
from pathlib import Path

from aws_cdk import App, Environment

from infrastructure.cdk.agentcore_config import AgentCoreDeploymentConfig
from infrastructure.cdk.agentcore_stack import AgentCoreFoundationStack, AnalyticsAgentRuntimeStack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--phase", choices=("foundation", "runtime", "all"), default="all")
    parser.add_argument("--outdir")
    args = parser.parse_args()
    config = AgentCoreDeploymentConfig.model_validate_json(args.config.read_text())
    app = App(outdir=args.outdir, analytics_reporting=False)
    env = Environment(account=config.account, region=config.region)
    if args.phase in ("foundation", "all"):
        AgentCoreFoundationStack(
            app, f"{config.resource_prefix}-agent-foundation", config=config, env=env
        )
    if args.phase in ("runtime", "all"):
        config.validate_artifact()
        AnalyticsAgentRuntimeStack(
            app, f"{config.resource_prefix}-agent-runtime", config=config, env=env
        )
    app.synth()


if __name__ == "__main__":
    main()
