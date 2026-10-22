---
name: market-data-delays
version: 1
applies_to: "market-data 3.x"
---
# Market data delays

1. Compare market-data latency with the matching-engine latency.
2. Check the most recent market-data deploy.
3. If the delay started after a deploy, roll back that deploy.
4. Recovery criterion: market-data latency below 10 ms in 3 consecutive readings.
