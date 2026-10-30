# Report — 7f: v0.9.11 is pinned, kinds adoption is 1, and four fields have two owners

**Date:** 2026-10-29
**Lane:** 7f (`doc-tools`)
**Branch:** `7f/sdk-v0911-kind-registrations` → **PR #192** (based on `main` at
`7ffb6a2`, so it gets a real verdict)
**Order:** SDK adoption packet, item 2 — *"doc-tools pins v0.9.11 and registers
kinds through `ContentKindRegistration` (7f) — kinds adoption goes 0 → 1."*

---

## 1. The order is done, and both of its preconditions were read from state

The packet's opening rule — *a status claim about a tag, merge or roll is read
from git/registry/helm state in the same message, never from a packet* — was
applied twice, and both checks came back positive **as measured**, not as
asserted:

* **The tag exists and is the code I measured.** `git ls-remote` returns
  annotated tag object `db7e9e35`; dereferenced it is commit **`2a0f951e`**,
  which is the sha now in `uv.lock`. The apparent mismatch between the tarball
  directory name and the lock sha was a tag-vs-commit artifact, resolved rather
  than waved through.
* **The ADR-0063 §1 blocker is cleared by the bump.** `ContentKindRegistration`
  had **8 fields at v0.9.8** and has **13 at v0.9.11**. §1's recorded finding —
  that `arrives_as` and `review_shape` *cannot be row fields* — was true of the
  old pin and is now false. It was cleared by shipping, not by argument.

Two commits, because the pin and the adoption fail differently and want
reverting separately: `49b7f1f` (pin) and `0cf4b87` (adoption).

## 2. The pin is the cheapest a pin gets — and it is still not zero

Measured per **consumed symbol**, which is this file's own convention, not per
tag distance:

| surface | diff v0.9.8 → v0.9.11 | consumed symbols |
| --- | --- | --- |
| `transport_auth` | 0 changed lines | identical |
| `service_identity` | 0 changed lines | identical |
| `interfaces` | +154 | both identical |
| `ingest` | +123 | `INGEST_STAGES`, `ContentKindUnregistered` identical |
| `provenance` | +319 | one widening, below |

Zero dependency changes: same eight hard deps, same `mcp<2` ceiling,
fastapi/uvicorn still extras-only, nothing added or removed. `uv.lock` moves
exactly three lines.

**The one behaviour change is a widening, and a widening is still a change.**
`OBTAINED_VIA` grew 5 rungs → 7 (`steward-corrected` in 0.9.10,
`steward-entered` in 0.9.11). `doc_tools/utils/ingest_provenance.py` re-exports
it as `Literal[OBTAINED_VIA]`, so **our stamp's accepted set widened by two
values we never write** — a row can now arrive at our validator carrying a rung
no code of ours produces, and pass. ADR-0041's Consequences section asks for
exactly this re-check on a provenance bump; this is the first time the ask has
been honoured against a real diff. `ProvenanceBlock`'s two new optional fields
are both forbidden under the rungs we do write, so no exposure there.

## 3. Adoption means the model became load-bearing, not that it got mentioned

Before this branch, `ContentKindRegistration` appeared in doc-tools in
**comments and one test**. `scripts/generate_kind_registrations.py` rendered
`registry/content_kinds/*.yaml` as hand-built strings, so the SDK's validators
ran only when a test chose to load the rows back — after the bytes were already
on disk. That is a check, not an adoption.

Now `doc_tools/utils/kind_registrations.py` projects `KIND_MAPPING` onto the
model **in the production package**, and the generator renders from those
objects. Building the registration is the step that produces the bytes, so a row
the SDK would refuse — empty `passes`, a duplicate in `outputs`, an event-branch
shape we cannot express — **raises instead of being written and rejected later
by whoever loads it.**

**The row payloads are byte-unchanged, all thirteen.** Only the generated header
comment moved (2 lines → 4). Verified by md5 over every row with comments
stripped, before and after: `5f4c22e2e610429d489bdcf84ad1ba7a` both times. This
is the result worth stating plainly: the adoption changes **where the bytes come
from, not what they say**, which is what makes it safe to land in front of the
cross-repo overlay seal and in front of any field migration.

## 4. THE FINDING: `arrives_as` has two owners, and they were written three days apart

Of the model's thirteen fields we set three — `kind`, `passes`, `outputs` — and
project two more where a row declares one (none does). The remaining eight stay
at their defaults, each for a reason recorded at the projection site. Four of
those eight are the finding:

> **The architect's ruling of 2026-10-24, amending 10-07** (recorded in
> `tests/test_overlay_kind_drift.py`): *"the platform owns what a kind IS
> (`kind`, `domain`, `arrives_as`, `review_shape`, `label`); doc-tools owns what
> it RUNS (`passes`)."*

> **iagent-mesh's own v0.9.11 changelog, dated 2026-10-21**, of `arrives_as`:
> *"ca adds the field, 7f fills in KIND_MAPPING's rows with it."*

**Both are live, and they disagree about who writes the field.** The changelog
instruction is three days older than the ruling that moved the field away from
this lane. This is the kind of collision that gets "resolved" by whoever edits a
file first, and then shows up a month later as drift that neither side can
explain — so this lane declines all four fields, states why at the projection
site, and **asks for a ruling** rather than filling them.

Measured from both trees before writing any of it: **nothing has filled any of
the four anywhere.** On platform master the overlay rows carry only
`kind`/`domain`/`passes`/`outputs` — no `arrives_as`, no `review_shape`, no
`label`. So nothing is broken today; the collision is latent, which is the
cheapest moment to raise it.

This changed the deliverable. I had already decided values for `arrives_as`,
`review_shape` and `label` across all thirteen rows. Reading the drift test's
docstring showed those fields belong to the other side of the mirror, and that
filling them here would have made this repo a **second source of truth for
another repo's fields** — precisely the drift the seal exists to catch. None of
it was written.

The other four declines:

* `branch`/`refresh` — no counterpart on `ContentKindEntry`. ADR-0063 §1 stands,
  unchanged by this pin: an event row is blocked on **our** plumbing, not the
  SDK's. All thirteen rows are documents and none sets `seeds_workflow`, so
  `branch` takes its `"document"` default honestly today.
* `parent_link_field` — **owed a measurement, not a decision.** Which field of
  our S1000D output holds the parent is a claim about our parser's output shape,
  and must be read off a real data module. Left unset rather than guessed.
* `id_namespaces` — no kind we register has a validatable ID prefix. A PCN
  number is the manufacturer's own string. `()` is the true statement, and the
  SDK's validator would hold us to anything else we declared.

## 5. The declines are pinned, so they cannot be mistaken for oversights

Three new arms in `tests/test_kind_registry.py`:

1. `test_the_rows_on_disk_are_the_sdk_projection` — loads the directory back
   through the SDK's own composer and compares **field for field**, not kind for
   kind. Closes the loop in the direction `--check` does not.
2. `test_the_platform_owned_fields_are_absent_by_ruling` — asserts the four
   names still **exist** on the model (if the SDK drops one, the ruling has
   nothing to attach to and that is a lane/ca conversation), then that every row
   leaves each at its model default, with the ruling quoted in the failure.
3. `test_the_projection_fills_exactly_what_doc_tools_owns` — `exclude_defaults`
   equals exactly the three fields we own.

Also retired two stale deferrals that the bump turned into falsehoods: the note
promising a `domain`-into-the-rows migration *"with the pin bump"* is marked
**WITHDRAWN** (the bump happened; the ruling moved the field), and the two
places that declined `review_shape` *because it did not exist at v0.9.8* now
record that reason as **expired** — the decline stands on ownership, which was
always the stronger of its two reasons. **A decline, not a deferral.**

## 6. Verification

```
tests/            1 failed, 2319 passed, 13 skipped, 16 deselected, 1 xfailed  (110.91s)
doc_tools_tests/  36 passed, 5 skipped  (7.73s)
```

The single failure is
`test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes`,
which reads the sibling repo's **working tree** instead of a pinned sha. It fails
identically on `main` without this branch, touches no SDK symbol, and is the
defect **PR #181** fixes. Both directories were run deliberately: CI invokes a
bare `pytest -q -rs` and `pyproject.toml` declares no `testpaths`, so
`doc_tools_tests/` is in scope there and a local `tests/`-only run would have
missed it.

Suite went **2316 passed** (pin alone) → **2319 passed** (with the three arms),
so the arms are the only new coverage and nothing regressed across the bump.

## 7. Traps hit, both already in memory, both cost real time

* **The libmagic hang.** `.venv/Scripts/python.exe -c "import doc_tools…"` under
  the Bash tool produced **no output** and had to be killed; the same import
  from PowerShell finishes in seconds. The rule in `CLAUDE.md` is right and it
  is not optional: *a run that produces no output is an interpreter-and-shell
  problem before it is a code problem.*
* **Scratchpad-root shadowing.** A stale `inspect2.py` at the scratchpad root
  shadowed the real `inspect2` package (reached via datahub → deprecated) and
  surfaced as an `IndexError` from inside library code. Fixed by moving the
  harness into `scratchpad/kh/`. Harnesses run from a **subdirectory**, never
  the scratchpad root.
* **`uv sync` prunes out-of-band installs.** It removed `en-core-web-sm==3.8.0`,
  which the container installs separately
  (`.github/workflows/build-container.yml:1173`). Confirmed no Python file
  imports it, then restored it by wheel URL so the local venv stays faithful to
  the image.

## 8. What is owed, and by whom

* **A ruling on the four fields** — `domain`, `arrives_as`, `review_shape`,
  `label`. The changelog (2026-10-21) says 7f fills `arrives_as`; the ruling
  (2026-10-24) says the platform owns it. **This lane cannot settle it by
  editing a file.** If the ruling lands on this side, arm 2 above is the one to
  delete, deliberately, with the ruling named.
* **`parent_link_field` for `s1000d-data-module`** — a measurement of our
  parser's output shape, owed by this lane.
* **`branch`/`refresh` plumbing** — `ContentKindEntry` needs both before any
  event kind can be registered. ADR-0063 §1's remaining answer.
* **#181** fixes the one red arm above; it is pending its container build.

---

**Files:** `pyproject.toml`, `uv.lock` (commit 1);
`doc_tools/utils/kind_registrations.py` (new),
`scripts/generate_kind_registrations.py`, 13 × `registry/content_kinds/*.yaml`,
`tests/test_kind_registry.py`, `docs/contracts/document-kind.md`,
`doc_tools/utils/content_kind.py` (commit 2).
