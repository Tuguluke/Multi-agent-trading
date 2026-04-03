#!/usr/bin/env python3
"""AWS CDK app — provisions all infrastructure for the energy trading desk."""

import aws_cdk as cdk
from stacks.storage_stack import StorageStack
from stacks.messaging_stack import MessagingStack
from stacks.compute_stack import ComputeStack
from stacks.monitoring_stack import MonitoringStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or None,
    region=app.node.try_get_context("region") or "us-east-1",
)

storage = StorageStack(app, "EnergyTradingStorage", env=env)
messaging = MessagingStack(app, "EnergyTradingMessaging", env=env)
compute = ComputeStack(
    app, "EnergyTradingCompute",
    ingestion_queue=messaging.ingestion_queue,
    agent_trigger_queue=messaging.agent_trigger_queue,
    env=env,
)
MonitoringStack(app, "EnergyTradingMonitoring", env=env)

app.synth()
