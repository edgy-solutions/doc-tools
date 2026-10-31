# report — 7f — the column-map contract was wrong in four places, and its own worked example was refused

Lane: `doc-tools/lane/7f`. Date: 2026-10-30. PR: **#198** (`7f/batch-profile-schema` → `main`).
Order: *"the batch chain continues (scrubber → schema → CLI against the column-map contract)."*
This is **link 2**, the schema. Link 1, the scrubber, is **#196**. Link 3, the CLI, is next.

## What shipped

| Path | What it is |
| --- | --- |
| `docs/contracts/batch-column-map.schema.json` | The shape. JSON Schema 2020-12, `$id` `…/batch-column-map/2.json`, `additionalProperties: false` at every level. Three `if`/`then` conditionals carry §5–6: `land` ⇒ `landing`, `landing` ⇒ `land`, `iso8601` ⇒ both. |
| `doc_tools/batch/profile.py` | Ten rules a JSON Schema cannot express, because they resolve against the field catalogue. |
| `registry/batch_profiles/pcn-ltb-by-part.yaml` | §10's worked profile as a validated file. |
| `tests/test_batch_profile.py` | 15 tests: one per finding code, the shipped profile at zero errors, the catalogue read, the refused-transform arm, §6's two-things arm. |

The validator reports **all** findings, never just the first — a shape error and a
catalogue error in the same profile both surface — and fails closed: any `error`
finding makes a profile unusable; a `warning` does not.

There is still **no exporter**, and nothing under `doc_tools/` imports
`doc_tools.batch`. `doc_tools/batch/__init__.py` says so in its docstring, so the
next reader does not have to grep for it.

## The finding: writing a validator measured the contract, and four things in it were wrong

Not incomplete — **wrong**. A validator is the first thing that ever resolved the
contract's words against the catalogue, and the contract lost four times.

1. **`source.field` is the catalogue `name`, not "the wire property."** §4 said the
   wire property. §9's gate resolves against the catalogue, whose only unique
   identifier is `name`; wire names are *not* unique — which is the very problem §4
   exists to solve. Had it been built as written, the discriminator would have been
   the ambiguous half of the pair.
2. **Six wire names are shared, not three.** `extracted_value` is shared by five
   fields, plus `field`, `evidence_ref`, `added`, `corrected`, `deleted`.
   `part.customer_mpn` (#191) is what moved it. **A transcription of §4's three
   would already have been wrong by five**, so the validator derives the set from
   the catalogue and the contract no longer lists it.
3. **58 fields, 33 served, 25 unserved** — not "28 of the 57". That count has now
   moved twice in a week. Nothing hardcodes it; the single assertion about it reads
   the file.
4. **§10's worked profile did not validate.** Its first column is `field: doc_id`.
   No catalogue field is named `doc_id`. The nearest, `header.doc_id`, is
   **unserved**, and §9 refuses an unserved field. The contract's own gate refused
   the contract's own example, at its first column, and nothing had ever run them
   against each other.

Both sides were corrected rather than either being quietly bent: the contract is at
**`contract_version: 2`** with an amendment table naming all four version-1 errors,
and the profile ships as a real file whose header records each correction.

## The second finding: what a profile can and cannot name of the document itself

Amending §9 measured something worse than the counts. **All eleven `header.*` fields
are unserved, every one with a null wire as well.**

**CORRECTION, 2026-10-31 — this section overstated its own finding, and the
overstatement is the interesting part.** What stood here said a profile has *no*
access to the document's printed identity: *"not the id, not the type, not the
revision, not the publication date… ingest keys, not document fields."* The id half
is **wrong**. The catalogue says so in the entry itself: `header.doc_id` carries
`"notes": "Served as notice.notice_id, so reachable under that name only."`, and
`notice.notice_id`'s producer is `baml:SustainmentHeader.doc_id` with
`review_json: header.doc_id`. **The two names are one producer field, so
`notice.notice_id` IS the printed document id.**

How it happened is worth naming, because it will happen again: the finding was
derived by filtering the catalogue on `served_by: null` and reading the names, and
**the `notes` field beside each one is where the catalogue records reachability
under another name**. A machine-read of one key produced a true count and a false
conclusion. The validator was never wrong — it resolves against `served_by` and
correctly accepts `notice.notice_id` — only the prose was.

What survives: the document's **type, revision and publication date** are genuinely
unreachable, each unserved with a null wire and no "reachable as" note, as are the
two verbatim source substrings and the two derived prose fields. So the §10 profile's
`notice.notice_id` is the **right** name rather than a fallback, and a human can
reconcile a fixture row against the printed notice after all.

**RULED 2026-10-31: Lane 1 serves the two header fields.** The ruling does not name
which two; the packet of the same date asks, and names `header.pub_date` and
`header.revision` as this lane's reading, since the id is already reachable. No
profile or code changes either way: `validate_profile` resolves `source.field`
against the catalogue and will accept them the moment `served_by` is set.

## `scope` → `field_scope`, landed with its first consumer

Lane 01's answer, placed today and committed with this work:

> yes. No iagent code reads the catalogue yet, so the rename costs nothing here, and
> it keeps the key from being read as an OAuth scope. **Rename it before anything
> consumes it.**

The validator is that first consumer, so the rename is in the same commit as the
thing that reads it, and no consumer ever read the old key. The catalogue is at
`catalogue_version: 2`: `field_scope` on all 58 fields, `field_scopes` as the
vocabulary block, and the seal in `tests/test_export_field_catalogue.py` renamed
with it.

The collisions entry now reads `"severity": "resolved-here"`, quoting the
authorisation, and records that **our** meaning is settled while cortex's and lane
fin's two meanings still collide with each other. That pair is lane 01's to settle;
nothing here touches it.

## Two dependencies declared, not inherited

`jsonschema` and `pyyaml` were importable in this venv **only transitively** —
`jsonschema` solely through dagster's `test-components` extra, which is not even a
hard dagster dependency, and PyYAML through `torch`/`timm`/`accelerate`. Building the
validator on them undeclared is exactly the failure this repo already paid for when
`iagent-mesh` masked `dag-tools`' undeclared `fastapi`. Both are in
`pyproject.toml` now, with the measurement recorded beside them.

### The lock, and a claim this report had to withdraw

The first commit on this branch said `uv.lock` was *"deliberately not
regenerated"*, on the strength of the standing finding that `uv sync` removes the
spaCy model and reds three golden tests. **That was wrong, and the `tests` job
DID fail on it — twice.** `.github/workflows/build-container.yml:686` runs
`uv sync --locked`, and `--locked` *asserts* that the lock and `pyproject.toml`
agree and fails loudly when they do not — the workflow's own comment block argues
for exactly that, deliberately, since 2026-09-19. Declaring a dependency without
locking it is not a deferral in this repo; it is a red `tests`.

**The evidence, read from the runs and not from the reasoning.** Three runs on
this branch:

| head | run | outcome |
| --- | --- | --- |
| `a6235a6` | 41165527292 | **failure** — `tests` / Install dependencies |
| `83ed40f` | 41165640782 | **failure** — same step |
| `6b52f3e` (the lock) | 41165828658 | **success** |

Both failures are the same line:

    error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
    hint: To update the lockfile, run `uv lock`.

So the correction is not a precaution. It is the fix for a red that had already
fired twice before anyone looked.

So the lock is regenerated, and the measurement says the fear did not apply:

- `uv lock` → `Resolved 383 packages`, **383 before and 383 after**.
- The diff is **four lines**: `jsonschema` and `pyyaml` each added to
  `dependencies` and to `requires-dist`. **No package block changed; no version
  moved.** Both were already in the resolution as transitive packages, so
  promoting them to direct resolves to the same pins.
- The spaCy finding is about **`uv sync`**, which rewrites the venv. **`uv lock`
  does not touch the venv** — only the lockfile. Applying a venv finding to a
  resolver command is the mistake, and it is the kind this lane keeps making:
  the finding was true and still did not say what it was taken to say.

## Measured

- `29 passed` — `tests/test_batch_profile.py` (15) + `tests/test_export_field_catalogue.py` (14), from PowerShell against `.venv/Scripts/python.exe`.
- The shipped profile: zero `error` findings, asserted.
- The catalogue read, asserted from the file: 58 / 33 / 25, and all six shared wire names.

## Not done, and named

- **Lane 01's answers 1–3 are not yet in the catalogue.** `header.pub_date` is
  served as the extraction's `notice_date`; `header_edit.*` and `row_edits.*` are
  "on the record, not exported"; `row_edit_counts.*` is stored nowhere; `mfr_source`
  is **derived** at `gateway.py:13404-13409`, not copied, so `header.mfr_source`
  stays unserved and the entry should carry the derivation. These are substantive
  content changes that would move the 33/25 counts, so they are deliberately a
  separate change from the rename and the validator.
- **Link 3, the CLI**, against this contract.
- The two queued findings stay queued, per the architect: runtime reads the registry
  once the platform serves it; the domain `if`/`elif` ladder becomes passes keyed by
  domain under ADR-0059. *"Not a retrofit now."*
