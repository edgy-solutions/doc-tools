# 7f — the event branch is projectable, and the `document` default was hiding a 422

**Date:** 2026-10-30
**Lane:** `doc-tools/lane/7f`
**Branch:** `7f/content-kind-event-branch` → **PR #197**, based on `main` at `e6d68d5`
**Order:** *"…and `branch`/`refresh` on ContentKindEntry so ADR-0063's event kinds can register."*

## Headline

ADR-0063 section 1's remaining answer is in. The 2026-10-28 measurement found
the SDK had an event branch **and we could not project it**; that half is now
closed. On the way, the change turned up a latent 422 that no row had tripped:
`registration_for` already projected `identity_field`/`seeds_workflow` whenever
a row set one, while `branch` did not exist and the SDK therefore read the row
as a `document` — where it **forbids** both. A row that set either would have
raised at registration rather than registering. It was harmless only because no
row set one.

## Measured

| What | Result |
| --- | --- |
| `tests/test_kind_registry.py` from PowerShell | **28 passed in 22.27s** (was 21 tests) |
| `scripts/generate_kind_registrations.py --check` | **exit 0**, `registry in sync with KIND_MAPPING (13 rows)` |
| `git status --porcelain registry/` | empty — all thirteen rows byte-unchanged |
| `registry_fingerprint()` | hashes `(kind, passes)` only; cannot move |

The thirteen rows are byte-unchanged because the generator emits `branch` only
when a row departs from `"document"`, and no row does. Emitting it
unconditionally would have passed every other arm in the file and rewritten all
thirteen — the default restated as data.

## What is pinned, and what deliberately is not

The per-branch required/forbidden rule is **not** restated in this repo. It
lives in the SDK's `ContentKindRegistration._branch_shape_is_consistent`, and
the new arms pin it as a **backstop**: what they assert is that the SDK still
refuses the shapes we rely on it to refuse —

 - an event row declaring `passes`/`outputs`;
 - a `refresh` whose template placeholder names a field other than the row's
   own `identity_field`;
 - a **document** row declaring `seeds_workflow` — the latent 422 above.

That is the second-source-of-truth failure this repo keeps paying for, declined
on purpose. The cost is that the arms break if the SDK's wording changes; they
assert on the substring in the message, not the exact text.

## Two readings worth keeping

**"Forbidden" means EMPTY, not ABSENT.** The SDK's check is
`if self.passes or self.outputs: raise`. So `registration_for` keeps passing
both unconditionally and an event row carrying `()` is accepted. No branching
was needed around them, and an arm says so.

**No row is added to `KIND_MAPPING`.** Lane 01 confirmed on 2026-10-28 that
ADR-0063's three event kinds are **iagent overlay rows** under
`policy/overlays/openddil-lab/content_kinds/`. A new arm asserts no registered
row declares the event branch today, so one appearing becomes a split of
ownership to settle rather than a quiet addition.

## Flagged, not fixed

`extractor_config` / `baml_function` / `target_ontology_class` are required
**positionally** on `ContentKindEntry` and meaningless on a kind that runs no
pass, so the synthetic event row in the tests takes `""` for all three —
`s1000d-data-module` already takes `""` for `baml_function` the same way.
Making them optional reorders a thirteen-row table and belongs in its own
change.

## Also corrected

`test_the_projection_fills_exactly_what_doc_tools_owns` carried two claims this
change falsifies — *"eight stay at their defaults"* (now ten) and *"`branch` /
`refresh` have no counterpart on `ContentKindEntry` at all"*. Both are corrected
in the commit that falsifies them, which is the rule this repo adopted after
shipping two merged PRs that claimed Helm was absent from CI.

## State

- **PR #197** — F4, CI dispatched (based on `main`, so it runs).
- **PR #196** — link 1 of the batch chain, the scrubber. `tests` **pass**
  (1m59s); `corpus-gate` skipping; `build-and-push` still running at the time
  of writing. Nothing red.

Next in the architect's order: the **schema** link, then the **CLI** link, both
against `docs/contracts/batch-column-map.md`.
