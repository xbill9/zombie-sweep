# Evidence — 2026-11-15

Figures for the write-up. Every number here comes from a command run on this date.

## Baseline scan

`zombiescan-baseline-2026-11-15.{txt,json}`: `zombiescan scan --all-regions` run from
`~/zombiescan/src` on a laptop, read-only.

- 184 findings across 17 regions
- Estimated waste $11.92/month ($143.04/year), list prices
- 36 s wall time for all 17 regions

These files hold the account ID and full resource IDs, so they are kept out of git (.gitignore).

## Running cost of the sweep

`cost.py` → `cost-2026-11-15.txt`. Prices come from the AWS Price List API
(`aws pricing get-products`, us-east-1); free tiers are not applied.

| Item | Unit price |
|---|---|
| Lambda compute | $0.0000166667 per GB-second (tier 1) |
| Lambda requests | $0.0000002 per request |
| Step Functions Standard | $0.000025 per state transition |
| DynamoDB on-demand writes | $0.625 per million WRU |
| S3 PUT | $0.005 per 1,000 |
| S3 Standard storage | $0.023 per GB-month |
| CloudWatch Logs ingest | $0.50 per GB |

Assumptions: one sweep a day (30 a month); 19 Lambda calls a sweep (17 regions,
Compute Optimizer reader, report builder) at 512 MB; each call takes 36 s, the whole
laptop scan time, so the figure is an upper bound; 60 state transitions; 185 DynamoDB
writes (one per finding plus a run record).

Result: **$0.22 a month, $0.0074 a sweep.** Measured waste is 54 times that.

Not priced: Secrets Manager and KMS per-call charges for those checks, CloudFront
delivery of the report. Compute Optimizer recommendations and EC2/ELB describe calls
are free.

## Compute Optimizer

`compute-optimizer-enrollment-2026-11-15.json`: status `Active`, since 2026-10-14.

Idle recommendations cover 12 types (EC2, Auto Scaling groups, EBS, ECS on Fargate,
RDS/Aurora, NAT Gateway, DynamoDB provisioned, ElastiCache, MemoryDB, DocumentDB,
WorkSpaces, SageMaker endpoints):
https://docs.aws.amazon.com/compute-optimizer/latest/ug/view-idle-recommendations.html

Trusted Advisor cost checks need Business Support or higher:
https://docs.aws.amazon.com/awssupport/latest/user/trusted-advisor.html

## Compute Optimizer, all regions

`compute-optimizer-idle-2026-11-15.txt`: `get-idle-recommendations` in each of the
17 enabled regions returned 0 recommendations and 0 errors.

## Deployed sweep

Stack `zombie-sweep`, us-east-1. Second run `b974c166-bd60-4e13-87f2-93aaa18af95a`
(the first failed every Compute Optimizer call on `maxResults=1000` and is kept as
`sweep-5cae23e0-….json` only for its zombiescan half):

- SUCCEEDED, 10:48:45.5 → 10:49:04.6 EST, 19.0 s
- 35 Lambda branches (17 zombiescan, 17 Compute Optimizer, 1 global), 0 errors, slowest 16.64 s
- 184 findings, $11.92/month, all zombiescan; Compute Optimizer 0; found by both 0
- All 184 findings are resource types outside Compute Optimizer's idle list
- 297 execution-history events, 56 state entries

`cost_measured.py` → `cost-measured-2026-11-15.txt`: billed Lambda time from the
functions' REPORT log lines, arm64 price $0.0000133334 per GB-second.
**$0.002583 a sweep, $0.0775 a month at one a day**, against the $0.22 upper bound.
