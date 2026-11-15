"""Read AWS Compute Optimizer's idle recommendations for one region.

Event: {"runId": str, "region": str}
Stores each recommendation in the same table and shape as zombiescan's
findings, tagged source=compute-optimizer, so the report can compare the two.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
TTL_DAYS = 90


def _recommendations(region: str):
    client = boto3.client("compute-optimizer", region_name=region)
    token = None
    while True:
        kwargs = {}
        if token:
            kwargs["nextToken"] = token
        page = client.get_idle_recommendations(**kwargs)
        yield from page.get("idleRecommendations", [])
        token = page.get("nextToken")
        if not token:
            return


def handler(event, _context):
    run_id = event["runId"]
    region = event["region"]
    started = time.monotonic()
    expires = int(time.time()) + TTL_DAYS * 86400
    count, total, errors = 0, 0.0, []

    try:
        recs = list(_recommendations(region))
    except Exception as exc:  # opted-out or unsupported region: record and carry on
        recs, errors = [], [f"{type(exc).__name__}: {exc}"[:300]]

    with TABLE.batch_writer(overwrite_by_pkeys=["runId", "sk"]) as batch:
        for r in recs:
            arn = r.get("resourceArn", "")
            resource_id = r.get("resourceId") or arn.rsplit("/", 1)[-1]
            savings = (
                r.get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value", 0.0)
            )
            count += 1
            total += round(float(savings), 2)
            batch.put_item(
                Item={
                    "runId": run_id,
                    "sk": f"compute-optimizer#{region}#{r.get('resourceType')}#{resource_id}",
                    "source": "compute-optimizer",
                    "check": f"idle-{r.get('resourceType', 'resource')}".lower(),
                    "resourceId": resource_id,
                    "resourceType": r.get("resourceType", "unknown"),
                    "region": region,
                    "reason": f"Compute Optimizer: {r.get('finding', 'Idle')}",
                    "monthlyCost": Decimal(str(round(float(savings), 2))),
                    "approximate": False,
                    "remediation": "",
                    "expiresAt": expires,
                }
            )

    return {
        "source": "compute-optimizer",
        "region": region,
        "findings": count,
        "monthlyCost": round(total, 2),
        "errors": errors,
        "seconds": round(time.monotonic() - started, 2),
    }
