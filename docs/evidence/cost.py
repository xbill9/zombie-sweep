# List prices from the Price List API, us-east-1, fetched 2026-11-15. Free tiers ignored.
LAMBDA_GBS=0.0000166667; LAMBDA_REQ=0.0000002; SFN_TRANS=0.000025
DDB_WRU=0.000000625; S3_PUT=0.000005; S3_GBMO=0.023; LOG_INGEST_GB=0.50
runs=30                      # one sweep a day
invokes=17+1+1               # 17 region scanners + Compute Optimizer reader + report builder
mem_gb=0.5; secs=36          # upper bound: each Lambda as slow as the whole measured laptop scan
transitions=60               # generous for Start, Map over 18 branches, Choice, report, Succeed
writes=184+1                 # measured findings + run record, each under 1 KB
puts=2; log_gb=0.0001        # report.html + findings.json; ~100 KB of logs a run
rows={
 "Lambda compute":  runs*invokes*mem_gb*secs*LAMBDA_GBS,
 "Lambda requests": runs*invokes*LAMBDA_REQ,
 "Step Functions":  runs*transitions*SFN_TRANS,
 "DynamoDB writes": runs*writes*DDB_WRU,
 "S3 PUTs":         runs*puts*S3_PUT,
 "S3 storage (5 MB)": 0.005*S3_GBMO,
 "CloudWatch Logs": runs*log_gb*LOG_INGEST_GB,
}
for k,v in rows.items(): print(f"{k:20s} ${v:.4f}")
t=sum(rows.values()); print(f"{'TOTAL / month':20s} ${t:.4f}   per sweep ${t/runs:.5f}")
print(f"measured waste found: $11.92/month -> payback ratio {11.92/t:.0f}x")
