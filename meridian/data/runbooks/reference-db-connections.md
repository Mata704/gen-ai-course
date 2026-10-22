---
name: reference-db-connections
version: 1
applies_to: "reference-db 14.x"
---
# Reference database: connection errors

1. Check the links from dependent services to `reference-db`.
2. Read the reference-db logs around the time the errors started.
3. List recent changes to `reference-db`. Configuration changes are a common
   cause of connection errors.
4. If a recent change explains the errors, roll it back. Restarting the
   clients does not fix a server-side limit.
5. Recovery criterion: client error rate below 1% in 3 consecutive readings.
