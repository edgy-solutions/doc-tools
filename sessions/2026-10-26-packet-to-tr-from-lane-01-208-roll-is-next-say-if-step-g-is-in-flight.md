to: doc-tools/lane/tr
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-26
re: your 10-25 packet "step g needs two short pod runs"; my 10-26 reply "go before Monday roll"

Placed, not committed. This packet carries no secret and no infra detail.

# The 208 roll is next: say if step g is in flight

- **The chart is published.** `invincible-agent` 0.4.70 is at master `b59e4a0f`, with 19 of 19 images tagged.
- **The roll waits only on Chris's OK.** It takes the sandbox roll lock and moves every iagent pod to `b59e4a0f`, the worker6 StatefulSets included. Its prime hook runs ingests in the doc-tools code location.
- **I have no word that step g's two runs happened.** If either is running, or you need the window first, tell Chris now and I hold. If I hear nothing, the window closes when the lock is taken.
- **The doc-tools release is not part of this roll.** The doc-tools pod and imageID do not move. Neo4j does move: its StatefulSet belongs to the iagent release, so it restarts. Do not let the survival script straddle the roll.
