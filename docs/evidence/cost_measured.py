# Measured sweep run b974c166-bd60-4e13-87f2-93aaa18af95a, 2026-11-15.
# Billed ms from the functions' REPORT log lines (two runs in the window, the
# first subtracted). Prices: AWS Price List API, us-east-1, free tiers ignored.
ARM_GBS=0.0000133334; REQ=0.0000002; TRANS=0.000025; WRU=0.000000625
PUT=0.000005; GET=0.0000004; LOG_GB=0.50
fns = {  # name: (MB, invocations, billed ms for this run)
    "scan":      (512, 36 - 18, 278216 - 140430),
    "optimizer": (256, 34 - 17, 35241 - 17122),
    "report":    (512, 2 - 1,   1631 - 594),
}
transitions = 112 // 2      # StateEntered events in the execution history
writes = 184 + 0            # one row per finding, Compute Optimizer returned none
puts, gets = 5, 1           # index.html + findings.json twice, history.json; history read
log_gb = 0.0001
runs = 30
per = {}
for n, (mb, inv, ms) in fns.items():
    per[f"Lambda {n}"] = mb / 1024 * ms / 1000 * ARM_GBS + inv * REQ
per["Step Functions"] = transitions * TRANS
per["DynamoDB writes"] = writes * WRU
per["S3 requests"] = puts * PUT + gets * GET
per["CloudWatch Logs"] = log_gb * LOG_GB
for k, v in per.items():
    print(f"{k:18s} ${v:.6f}/sweep  ${v*runs:.4f}/month")
t = sum(per.values())
print(f"{'TOTAL':18s} ${t:.6f}/sweep  ${t*runs:.4f}/month (daily)")
print(f"waste found $11.92/month = {11.92/(t*runs):.0f}x the sweep's cost")
