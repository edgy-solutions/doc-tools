# ADR-0100 — doc-tools is a Dagster code location, not a service

**Status:** accepted + built
**Date:** 2026-10-16 (ruled, F2) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/api/app.py:1-10` — a module docstring, which was the **only** written
statement of this ruling before this record
**Related:** [ADR-0101](ADR-0101-processable-kinds-are-published-not-served.md) (the reversed
route that makes this possible), [ADR-0102](ADR-0102-assets-and-declarative-components.md)

## Context

doc-tools holds a Starlette app (`doc_tools/api/app.py`) that serves this image's processable
kinds, and the repository contains a Deployment with `containerPort` naming and probes. A reader
arriving at either of those concludes that doc-tools exposes HTTP — and then looks for the
Service, the ingress, or the reason the probes point at nothing.

There is no Service. The one container in the deployed pod runs `dagster api grpc -p 3030` and
starts no ASGI server; `charts/` references `api/app.py` nowhere. Measured at the pin: the chart
has no reference to that module at all.

The mistake this record prevents is not a design error, it is a **wasted investigation** — and
worse, a plausible repair. Someone who finds an app that nothing serves and probes that name a
port nothing listens on has every reason to "fix" it by wiring the app into the chart, which
would add a container, a Service and a second definition of a payload that already has one.

## Decision

**doc-tools is a Dagster code location. It has no HTTP surface, by ruling, and that is not an
omission.**

- The container runs `dagster api grpc -p 3030`. Nothing else.
- `doc_tools/api/app.py` is kept in the tree **deliberately unserved**: it is the same
  `ingestable_kinds()` payload behind a transport a human can call by hand, so the payload has
  exactly one definition.
- The Deployment's `containerPort` and probe naming are **left alone** until the day a port
  actually exists. Renaming them to match a port that does not exist would be a cosmetic change
  to a live manifest.

The ruling is recorded as F2 of 2026-10-16, and the posture rule that applies *the day it is
served* is in the same docstring — so the record of what to do then travels with the code.

## Consequences

- There is no HTTP attack surface, no Service, no ingress and no TLS question for this workload.
- Anything that needs doc-tools' answer gets it by the **push** route
  ([ADR-0101](ADR-0101-processable-kinds-are-published-not-served.md)), not by calling it.
- A reader who finds the app, the `containerPort` or the probes and concludes "this serves HTTP"
  is wrong, and this record is the place that says so. The docstring says so too, which is why
  the status is `built` as well as `accepted` — but a docstring only helps a reader who already
  opened that file.
- If doc-tools ever *does* serve, the posture rule in `app.py` applies and this record is
  superseded rather than quietly contradicted.

## Alternatives considered

- **Wire the app into the chart and serve `GET /kinds/processable`.** Rejected by the ruling:
  the pull route needs a container, a Service, a probe that means something, and a consumer that
  polls. The push route needs none of them, and Lane 1 wants the list *when it changes*, not
  when it asks.
- **Delete the app, since nothing serves it.** Rejected: the payload would then exist only
  inside the publisher, and a future third-party consumer — or a human checking what this image
  believes it can process — would have nothing to call. One definition, two transports, one of
  them deployed.
- **Rename the `containerPort` and the probes so the manifest stops implying HTTP.** Rejected
  for now: it is a change to a live Deployment that buys tidiness and risks a roll. The ruling
  parks it until a port exists.
