"""Every doc-tools workload must refuse the stateful-core's nodes.

WHY THIS FILE EXISTS. On 2026-10-07 the revision-36 roll placed the new pod on
`k3s-worker6`, whose filesystem had gone read-only; the pull failed with
`failed to commit snapshot ...: commit failed: read-only file system` and the
pod sat Pending until the node recovered and it rescheduled itself. Three
`doc-tools-corpus-gate` pods -- the 07:00Z runs of Oct 5, 6 and 7 -- had been
placed on that same node, which had flapped five times in 4d20h.

THE DEFECT WAS NOT THE SICK NODE. It was that this chart was the only one still
permitted to land there. `k3s-worker6` and `k3s-worker1` carry
`iagent.io/stateful-node`, the label marking the nodes that hold the
stateful-core's local-path PVs (MinIO, Keycloak, Restate, Weaviate -- volumes
pinned by nodeAffinity, which therefore cannot move). The invincible-agent
chart already refuses those nodes for everything that is not stateful-core:
`invincible-agent.avoidStatefulNodes` in its `templates/_helpers.tpl` is
included by 20 of its templates, and the live dag-tools and dagster pods were
measured carrying the matchExpression. doc-tools was the gap.

WHAT IS TESTED, and what is deliberately not. That BOTH workloads this chart
ships -- the Deployment and the corpus-gate CronJob -- render a REQUIRED
nodeAffinity that excludes the label. The CronJob is the one that matters most
and the one easiest to forget: it reads `.Values.affinity` from a second place
in the chart, so a change that fixes only the Deployment leaves the nightly
authority measurement still landing on a stateful node.

These do NOT assert where the setting lives. It is in values-sandbox.yaml today
because the label is applied out-of-chart per cluster, but `DoesNotExist` is a
no-op wherever the key is absent, so promoting it to values.yaml would be a
safe improvement -- and a guard that failed on that promotion would be a guard
blocking the thing it wants. The assertions hold either way.

Shells out to the real `helm` and skips without it, for the reasons given at
length in test_chart_image_pin_guard.py -- a guard asserted against template
TEXT would be satisfied by a chart that no longer parses.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "charts" / "doc-tools"
HELM = shutil.which("helm")
requires_helm = pytest.mark.skipif(HELM is None, reason="helm binary not on PATH")

LABEL = "iagent.io/stateful-node"
#: The two kinds this chart schedules. The test-connection Pod is a `helm test`
#: hook -- it is not in the release manifest, pulls busybox rather than our
#: image, and runs only when someone asks for it, so it is out of scope here.
SCHEDULED_KINDS = ("Deployment", "CronJob")


def render(values_file="values-sandbox.yaml"):
    """helm template the chart with a committed values file. Returns the docs."""
    cmd = [HELM, "template", "t", str(CHART), "-f", str(CHART / values_file)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, f"render failed:\n{p.stdout}{p.stderr}"
    return [d for d in yaml.safe_load_all(p.stdout) if d]


def pod_specs(docs):
    """(kind, name, podSpec) for every workload that schedules a pod."""
    out = []
    for d in docs:
        kind = d.get("kind")
        if kind not in SCHEDULED_KINDS:
            continue
        name = (d.get("metadata") or {}).get("name", "?")
        if kind == "Deployment":
            spec = d["spec"]["template"]["spec"]
        else:  # CronJob
            spec = d["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        out.append((kind, name, spec))
    return out


def stateful_node_terms(spec):
    """Every matchExpression in a REQUIRED nodeAffinity that names the label."""
    aff = (spec.get("affinity") or {}).get("nodeAffinity") or {}
    req = aff.get("requiredDuringSchedulingIgnoredDuringExecution") or {}
    terms = []
    for term in req.get("nodeSelectorTerms") or []:
        for expr in term.get("matchExpressions") or []:
            if expr.get("key") == LABEL:
                terms.append(expr)
    return terms


@requires_helm
def test_BOTH_workloads_refuse_the_stateful_nodes():
    """The Deployment and the CronJob, not just whichever one was remembered."""
    specs = pod_specs(render())
    kinds = {k for k, _, _ in specs}
    assert kinds == set(SCHEDULED_KINDS), (
        f"expected to find {SCHEDULED_KINDS}, found {sorted(kinds)} -- if a new "
        "workload was added to this chart it needs the rule too"
    )
    for kind, name, spec in specs:
        terms = stateful_node_terms(spec)
        assert terms, (
            f"{kind}/{name} renders no REQUIRED nodeAffinity excluding {LABEL}. "
            "It can be scheduled onto a node holding the stateful-core's "
            "local-path volumes, which is how the 2026-10-07 roll stalled."
        )


@requires_helm
def test_the_rule_matches_on_PRESENCE_not_on_a_value():
    """`DoesNotExist`, not `NotIn ["true"]`.

    The key's presence is the signal and its value carries no meaning -- that is
    the upstream helper's documented contract. A value match would readmit a
    node labelled anything other than the one string compared against, which is
    a silent hole rather than a loud failure.
    """
    for kind, name, spec in pod_specs(render()):
        for expr in stateful_node_terms(spec):
            assert expr.get("operator") == "DoesNotExist", (
                f"{kind}/{name} matches {LABEL} with "
                f"{expr.get('operator')!r} and values {expr.get('values')!r}; "
                "presence is the contract, so DoesNotExist is the only operator "
                "that closes the hole"
            )
            assert "values" not in expr, (
                f"{kind}/{name} supplies `values` alongside DoesNotExist; "
                "Kubernetes rejects that combination at admission"
            )
