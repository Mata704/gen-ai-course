---
name: order-gateway-latency
version: 2
applies_to: "order-gateway 2.4.x"
---
# Order gateway latency (v2)

Since 2.4.0 the gateway runs independent instances. Restarting the whole
service drops every open member session; prefer acting on a single instance.

1. Read the gateway metrics for the last 5 ticks, per instance.
2. Check the links to `reference-db` and `matching-engine`. If a link is down
   or degraded, do not restart the gateway: investigate the dependency and
   recent changes first.
3. If a single instance shows memory above 90%, restart that instance only.
4. Recovery criterion: gateway latency below 20 ms and error rate below 1% in
   3 consecutive readings taken after the action.
