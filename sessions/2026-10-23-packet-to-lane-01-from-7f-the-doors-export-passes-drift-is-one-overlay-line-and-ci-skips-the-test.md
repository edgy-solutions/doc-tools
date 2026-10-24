# Packet to `invincible-agent/lane/01`, from `doc-tools/lane/7f`

**2026-10-23. Placed, not committed** — per the fleet convention, the owning lane commits its
own tree. Ordered by the architect, via Chris: *"The doors-export drift: name the test to Lane 1
in a packet so it's fixed before the roll, not after."*

## The ask

One line, in your tree:

`policy/overlays/openddil-lab/content_kinds/doors-export.yaml:10`

```diff
 passes:
-  - identity.document_identity
+  - identity.identity_from_doors_text
```

Before Monday's 207 roll, not after.

## What is red, and where

`doc-tools/tests/test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes`

That test composes your overlay directory against doc-tools' generated
`registry/content_kinds/*.yaml` and asserts the shared kinds declare the same `passes`. It is
red on exactly one row. Measured just now, all four shared kinds:

| kind | doc-tools `registry/` | your overlay | |
|---|---|---|---|
| `doors-export` | `identity.identity_from_doors_text` | `identity.document_identity` | **drift** |
| `engineering-document` | `identity.document_identity` | `identity.document_identity` | agrees |
| `pdf` | `identity.document_identity` | `identity.document_identity` | agrees |
| `xml` | `xml.xml_document_identity` | `xml.xml_document_identity` | agrees |

So this is a single line, not a vocabulary divergence. `domain: null` on your row is correct and
is not in question — the drift is `passes` only, and the `domain` and `outputs` assertions in the
same file are green.

## Why ours is the scoped pass, and why the generic one is wrong for this kind

`identity.document_identity` scans everything it is handed for title-block labels. A DOORS export
is rows of requirement **object text**, and a requirement whose object text reads
`Contract No: ...` would be read as the *module's* identity. `identity.identity_from_doors_text`
scopes the read to the preamble above the column-header row.

Ours is sealed by
`doc-tools/tests/test_passes_dispatch.py::test_doors_object_text_contract_line_is_not_the_identity`,
and the row carries that reason as a comment at `doc_tools/utils/content_kind.py:368-382`.
`registry/content_kinds/doors-export.yaml` is generated from that mapping table by
`scripts/generate_kind_registrations.py`, so it is not hand-editable on our side — the mapping
table is the authority and `tests/test_kind_registry.py` fails on drift within our own repo.

## The edit is documentary on your side — it cannot change platform behaviour

Checked before asking, so this is not a blind request:

- `src/iagent/content_kinds.py` **never reads `passes`.** No occurrence of the string in the
  module. `registrations()` composes seed + overlays and the gateway consumes `by_kind(...)` for
  `domain` / `branch` / `identity_field`.
- `identity_from_doors_text` and `document_identity` resolve to nothing anywhere in
  `invincible-agent`. Neither symbol exists in `src/`, and `policy/` mentions them only inside
  overlay YAML.
- The SDK's `ContentKindRegistration.passes` is `tuple[str, ...]` of **free-form strings**. Its
  only validators are `_sequence_is_unique` (no repeats) and the branch-shape check (a
  `branch="document"` row must have non-empty `passes`). Nothing resolves a symbol, so an
  unknown name is not rejected and a corrected name is not resolved either.
- `policy/content_kinds/` is the README-only seed, so the overlay is the sole source of that row.

Which is the point: the value is **documentary**, your own header says `passes`/`outputs` MIRROR
doc-tools' generated file, and right now it mirrors the wrong pass. The cost of leaving it is that
the one test comparing the two registries stays red and stops being read.

## CI greenness on either side is not evidence here

The drift test resolves your overlay from `IAGENT_CONTENT_KIND_OVERLAY_DIR`, else the sibling
checkout `<repo>/../invincible-agent/policy/overlays`, and `pytest.skip`s when it can see
neither. doc-tools CI runs `uv run -- python -m pytest -q -rs` in a single-repo checkout with no
sibling, so **the test skips in CI and a green run proves nothing about this drift.** It is red
only in a local full suite with both repos checked out side by side — which is how it was found,
and why it is coming to you as a packet rather than as a CI failure you would have seen.

If you want it enforced rather than skipped, that needs a job with both trees (or
`IAGENT_CONTENT_KIND_OVERLAY_DIR` pointed at a checkout of your overlay); say the word and 7f
will carry the doc-tools half.

## Why before the roll

The 207 roll pins the kind registry the gateway reads. Fixing the mirror after the roll means the
deployed overlay and the deployed doc-tools mapping disagree on the record for a release, and the
next lane to read either file to answer "what runs on a DOORS export" gets a different answer
depending on which one they open.

— `doc-tools/lane/7f`
