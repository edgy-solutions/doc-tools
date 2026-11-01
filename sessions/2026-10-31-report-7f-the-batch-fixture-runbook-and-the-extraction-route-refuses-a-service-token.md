# report — 7f — the batch fixture runbook, and the extraction route refuses a service token

Lane: `doc-tools/lane/7f`. Date: 2026-10-31. PR: **#202** (`7f/batch-scorecard` → `main`).
Order: *"the work runbook for the batch fixture (invocation, the private overlay
file layout, truth-set format, what the scorecard shows, what never leaves the
box), synthetic example end to end on sandbox with the ten-notice corpus as the
'private' set. Cut v0.2.3 after so work can pull it."*

#199, #200 and #201 merged first, on the same order.

## What shipped

| Path | What it is |
| --- | --- |
| `doc_tools/batch/score.py` | The scorer. Two artifacts: a scorecard that may leave the box, a detail file that may not. |
| `tests/test_batch_score.py` | 12 arms, one per rule, including one that walks the emitted JSON and refuses any string that is not a column name, the profile name, or closed vocabulary. |
| `docs/batch-fixture-runbook.md` | The operator runbook, written for the work side. |
| `AGENTS.md` | A pointer to both, because an unfindable runbook is not delivered. |

## The runbook had to invent two things, because the tree had neither

Measured before writing: **nothing in the tree used the words "scorecard" or
"truth set"** — zero hits, repo-wide. So "what the scorecard shows" could not be
documented; it had to be built first, which is why this PR carries code.

**The truth-set format, and the one convention it stands on.** A value must
match byte for byte. An **empty cell asserts nothing** — because the work side
types this by hand off the notices, and a half-filled truth set is the normal
case, not a defective one. `<empty>` is reserved and asserts the cell *is*
empty, which is how "there genuinely is no replacement part" gets said as a
finding rather than read as a gap. In a key column `<empty>` also names the
empty string, since a no-parts row carries an empty part key.

The scorer **never normalises before comparing** — not case, not whitespace, not
date form. The exporter already refuses to guess at `05/12/2023`; a scorer that
normalises again would hide the very defect the refusal exists to expose.

## The defect this nearly shipped with, twice, at two levels

A rate over joined rows alone reads 100% while a third of the corpus never came
out. That is the trap the whole design exists to prevent, and it was caught in
`totals` — and then **reproduced one level down**: the first draft kept
unexported rows out of the per-column counts, so
`columns["Replacement MPN"].rate` read 1 of 1 while a whole notice was missing.
The per-column block is the half an operator actually acts on, so hiding the
misses there is worse than hiding them in the total.

Corrected before commit. An unexported truth row's asserted cells now count
against the column they name, in a `not_exported` bucket, and there is **one**
rate definition with **one** invariant, asserted per column and in totals: the
five buckets sum to `asserted`, and `rate` is always `match / asserted`.

Worth naming as a pattern: the fix for a misleading aggregate is not a correct
aggregate, it is an invariant that ties the aggregate to its parts. The first
version had the right number in the right place and still misled.

## Safety is a construction property here, not a review step

Two files, not one with a flag, because a filter you have to remember to apply
is a filter that gets forgotten once.

| File | Carries | May be shown |
| --- | --- | --- |
| `--scorecard` | integers, floats, profile column names, closed vocabulary | **yes** |
| `--detail` | expected and got values of every disagreement | **no** |

The test walks the emitted JSON and fails on any other string, so the scorecard
cannot drift into carrying a value. The detail file announces itself in its own
first line, above the header, so a file opened out of context still says what it
is. Both commands keep the same rule on stderr: line numbers, counts, column
names and error codes, never a cell value — so a transcript of a run is
shareable even though its outputs are not.

Verified on the real end-to-end artifacts, not only in tests: the emitted
`card.json` matched zero occurrences of any ingest id, any MPN, or any notice id.

## Measured against sandbox, and all three findings changed the runbook

Probed from inside `pod/doc-tools-65766ddbdc-46bgv` — the only place the
Keycloak client secret exists, and it must never be materialized locally. The
token minted fine. All ten corpus `ingest_id`s:

**1. The route is dropper-scoped and refuses a service identity.**

    403 {"error":"not_entitled",
         "message":"a service reads only the drops it seeded as a declared delegate"}

Five of ten, under this repo's own `svc:doc-tools`. So **no cron, sensor or
service account can assemble a batch fixture** — a human with access runs it.
That is not an obstacle for the work side, who drop their own notices, but it
had to be established before a runbook could tell anyone how to fetch. It is now
the runbook's "fetch as yourself, not as a service" section.

**2. An `ingest_id` is derivable, confirmed live rather than inferred.** It is
`sha256:` plus the sha256 of the document bytes. The proof is in the split: five
returned **403 and not 404**, and a 403 requires the route to have found the
drop and read its seeder. So those five resolve under the content-derived id.
This is the live half of a finding whose other half is that
`iagent-mesh-sdk` does not validate that shape at all — the form is right *and*
unvalidated, which is why it can drift silently.

**3. Five of the ten are `ingest_not_found` — unknown to cortex-bff entirely.**
A question for lane 01, below. Not a defect of the id form.

**And `doc_tools/batch` is in no deployed image** (`ls /app/doc_tools/batch` →
no such directory). The batch chain has never been inside a pod. That is the
design — saved responses, no network, no credentials — and it is why the
delivery is a release and not a pin bump.

## The end-to-end

The ten-notice corpus standing in for a private set: each notice's **real**
`ingest_id`, synthetic values, in the layout the runbook prescribes. Not in this
repo and not in any git tree.

- `wrote 19 row(s)`, exit 0, with the `inherited_doc_level` note firing on two
  selected rows in `LTB Date` — which is the point of that note: a column of
  part LTB dates would otherwise read as though every date were found per part.
- Scored against an 8-row half-filled truth set: `totals.rate=0.7273`, exit 0,
  `truth_only: 1`, one `mismatch`, two `not_exported` cells,
  `exported_only: 12` and correctly **not** counted against the score.
- `52 passed in 18.03s` — `tests/test_batch_score.py` (12),
  `tests/test_batch_cli.py` (25), `tests/test_batch_profile.py` (15), from
  PowerShell against `.venv/Scripts/python.exe`.

Only the scorecard is quoted anywhere, including here. That is the rule the
runbook exists to state, so the report keeps it.

## A question for lane 01 — half the ten have no extraction on the route

Five of the ten corpus documents return `ingest_not_found` from
`GET /ingest/{ingest_id}/extraction`, under ids whose form is confirmed correct
by the other five.

**It correlates with nothing structural in the corpus block, which is the useful
part.** Checked every field that block carries — `bytes`, `filenames`,
`inbound_copies` — against the split (present = documents 2, 4, 7, 9, 10;
absent = 1, 3, 5, 6, 8):

| | present (403) | absent (404) |
| --- | --- | --- |
| `bytes` | 129,620 – 480,972 | 32,264 – 417,830 |
| `filenames` | 2, 1, 1, 1, 1 | 1, 1, 1, 1, 1 |
| `inbound_copies` | 4, 1, 1, 1, 1 | 7, 3, 1, 1, 1 |

**The duplicate-drop hypothesis is ruled out**, and it was the obvious one:
multiply-dropped documents sit on *both* sides (4 copies in the present group, 7
and 3 in the absent one), and the single document stored under two filenames —
the Diodes pair — **is present**. So neither re-dropping nor double-naming
explains absence.

The one dimension with any visible ordering is size: the three smallest
documents of the ten are all absent, below the present group's minimum. I am
**not** offering that as a finding. The ranges overlap across most of their
length, n is 10, and no mechanism makes a 32KB notice unknown to a route that
serves a 418KB one. It is recorded so the next person does not re-derive it and
mistake it for a lead.

The question: are these five absent because they were never promoted through
cortex-bff, or because their drop is recorded under a different key there? We
cannot tell from this side, and it matters for the batch path, because a work
notice that ingests fine and is then `ingest_not_found` is a fixture that cannot
be built with no error to explain why.

## Not done, and named

- **`pyproject.toml:3` and `uv.lock:1725` both still declare
  `version = "0.1.0"`**, as they did through v0.2.0, v0.2.1 and v0.2.2. Cutting
  v0.2.3 the same way is consistent rather than new. A bump needs both files,
  i.e. a `uv lock` run, because CI runs `uv sync --locked` and `--locked` fails
  on a mismatch — a red that has already fired twice on this lane. Queue item.
- Lane 01's catalogue answers 1–3 stay **held by our own published word** until
  they confirm `header.pub_date`: our 10-31 packet says we will land answers 1–3
  and the serving in one change.
- The two `contract_version: 3` gaps stay unfiled.
- The gate written-arm vs `mfr_agreement` contradiction still needs a ruling.
