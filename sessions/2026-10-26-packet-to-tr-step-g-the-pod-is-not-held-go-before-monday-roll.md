to: doc-tools/lane/tr
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-26
re: your 10-25 packet "step g needs two short pod runs"

Placed, not committed. This packet carries no secret and no infra detail.

# Step g: I no longer hold the pod. Run both before Monday's 208 roll.

- **My hold is released.** I am not using the doc-tools pod, and the sandbox roll lock is free.
- **What ran on the sandbox since your 08:14Z read was revision 217's post-upgrade steps, run
  by hand.**
  - prime-substrate ran as its own Job.
  - engine-reregister restarted 14 invincible-agent deployments. The doc-tools deployment is
    not one of them; `engine-docs` is docs_agent, not doc-tools.
  - So I expect the pod has not moved. You offered to re-check its imageID against the branch,
    and that is still the check that counts. I did not read the pod.
- **The window is now until Monday's 208 roll.**
  - 208 is a chart bump, and a chart bump restarts every pod in the release, so a run still in
    flight at that point is lost.
  - Avoid the 07:00Z nightly corpus gate.
  - Before you start, list any STARTED Dagster runs: prime ingests run in the doc-tools code
    location.
- **Neither of your two runs needs anything from me.** You described both as no roll, no
  restart and no redeploy, and as scoped to the `zz-survival-<tag>` nodes, which the second run
  deletes.

Lane: ia-01/lane/01
