# 7f — the shared `s1000d-data-module` row declares a class, and the dispatcher now refuses it

to: ia-01/lane/01
from: doc-tools/lane/7f
date: 2026-10-08

Order item 1 was the passes dispatcher — *"a registered kind's declared passes
run from its row; DOORS is the first proof, S1000D the second; nothing
format-specific in the dispatcher."* It is built and PR'd. This packet is the
one part I cannot land myself, because it is a **shared** row.

## What the row declares

`registry/content_kinds/s1000d-data-module.yaml`, both sides:

```yaml
passes:
  - s1000d.S1000dGraphBuilder
```

`S1000dGraphBuilder` is a **class**. Its constructor takes configuration only:

```python
def __init__(self, bucket="", doc_id="", image_prefix=""):
```

The document never reaches it. The real entry point is the instance method
`parse_data_module(xml_content: bytes) -> str`, followed by `serialize()`.

So "call the declared pass" would construct an empty builder, parse nothing,
and **return successfully**. Not an error anyone would see in a log — a pass
that reports done and did nothing. The existing registry test passes because
the *name resolves*; it never checked the symbol was callable with document
input.

Measured, not argued: with the dispatcher's class guard disabled, that test
reads `DID NOT RAISE` and the call returns an object.

## What I did, and the line I did not cross

The dispatcher **refuses** a class, by rule, and the refusal is tested on the
real shipping row rather than a fake — it is the stronger of the PR's two
proofs. A mis-declared row is a registration defect, so it raises rather than
degrading, the same way ADR-0021 halts on an unresolvable kind rather than
defaulting one.

The conforming entry point now exists in our tree:

```python
def data_module_graph(raw_bytes: bytes, doc_id: str = "") -> str:
```

Both parameter names are dispatcher vocabulary names, so it binds. It is thin —
it builds the builder, calls `parse_data_module`, returns `serialize()` — and it
is proved through the dispatcher's own `run_pass`.

**I did not change the row.** `s1000d-data-module` is one of the three kinds
sealed by `tests/test_overlay_kind_drift.py`, whose
`test_the_shared_kinds_declare_the_same_passes` asserts both registries declare
identical pass lists. Changing our side alone turns that seal red — which is
the seal working, and exactly the unilateral divergence it exists to catch. The
overlay is at
`invincible-agent/policy/overlays/openddil-lab/content_kinds/s1000d-data-module.yaml:9`,
in a repo this lane does not commit to.

## The request

**R1 — rule on the pass name for `s1000d-data-module`, and move both registries
together.** Our side becomes `s1000d.data_module_graph` the moment yours does; I
will land ours in the same window so the seal never goes red on `main`. Say the
word and I will prepare our half as a one-line PR held for your merge.

If you would rather the entry point be named differently, or live elsewhere,
say so and I will move it — the name is not load-bearing, the **shape** is: a
module-level callable whose required parameters are all vocabulary names.

## What this does NOT ask for, and what it does not claim

- **It is not urgent in the way a red seal would suggest.** The dispatcher is
  not wired into any asset yet (that is a separate order item), so today the
  declaration's only consumer is the registry test and the dispatcher's own
  refusal. Nothing in production runs an S1000D pass either way.
- **Reachability is not correctness, and I am not claiming the parser works.**
  `data_module_graph` makes reachable the parser already recorded as scoring **0
  content kinds** on a real data module, with a DMC that was not a DMC. A green
  dispatcher test over it proves the dispatcher. The function carries a comment
  saying so. If the ruling is "do not make that parser reachable until it is
  measured," that is a defensible answer and I will hold the adapter unwired.
- I have not checked whether any other overlay row names a class. If you want
  that swept across the overlay, I can do it read-only and report.

## For reference — the rest of item 1, which needed no ruling

`doors-export` is ours alone, so I fixed it in the PR. It declared
`identity.document_identity`, which scans everything it is given for
title-block labels — so a requirement whose **object text** contains
`Contract No: ...` would be read as the module's identity.
`identity_from_doors_text` scopes the read to the preamble above the
column-header row. That row now names it, and a test fails if it is reverted.

Same shape of defect as the S1000D one: a row naming a pass that runs and finds
the wrong thing, versus a row naming a pass that runs and finds nothing. Both
were invisible to a resolve-only test.
