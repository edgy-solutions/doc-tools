# Runbook — building a batch fixture from your own notices

For the work-side operator. You have a set of notices nobody else may see, and
you want a spreadsheet of rows out of them plus an honest number for how right
those rows are. This is how, and what of it may be shown to anyone.

Two commands do the work. Everything else here is about the files you put around
them.

## Before you start

You need three things. Only the first comes from this repo.

| | What | Where it comes from |
| --- | --- | --- |
| 1 | the exporter and the scorer | this repo, `v0.2.3` or later |
| 2 | a saved extraction per notice | you fetch them, see below |
| 3 | a column-map profile and a truth set | you write them, see below |

**Neither command touches the network.** The exporter takes *saved* extraction
responses and nothing else; the scorer does not even read the field catalogue.
That is deliberate: a tool that can fetch is a tool that can be pointed at prod
and piped into a transcript.

### Getting item 1 onto your box — and why a bare `python` will hang

Both commands are `python -m doc_tools.…`, so they import the `doc_tools`
package, and `doc_tools/__init__.py` ends with `from .definitions import defs`.
That pulls in the whole extraction stack — Dagster, `unstructured`,
`python-magic`, tesseract detection — for two tools that need none of it. There
is no lighter entry point today. So:

    git clone https://github.com/edgy-solutions/doc-tools
    cd doc-tools
    uv sync
    .venv/bin/python -m doc_tools.batch.cli --help      # .venv\Scripts\python.exe on Windows

`v0.2.3` is the floor for the *tools*, not an instruction to check it out. Read
this runbook from `main` and run from `main` unless you have a reason not to: a
`git checkout v0.2.3` also rolls this page back to the version that did not yet
warn you about the paragraph below.

**Run them through that `.venv` interpreter, never a bare `python` or `py` from
your `PATH`.** This is not style. A system interpreter loads a different
`python-magic`/libmagic pairing and **blocks for ever at import**, in
`magic/compat.py`: no output, one core pegged, and the process outlives your
shell. You will read it as a hung export of your own data. It is the import, and
it happens before either tool sees a single file of yours.

Two more things to expect, both measured 2026-11-03 and neither a fault:

- **`--help` takes about 36 seconds**, and so does every real invocation before
  it starts work. 13 s of that is `import doc_tools` alone. Budget for it; do
  not conclude the tool is stuck until well past a minute.
- **It prints `Found and configured tesseract at: …` to your terminal.** That
  line comes from the extraction stack being imported, not from anything
  reading your notices. Nothing in it is yours.

If the 36 seconds or the hang is unacceptable for your workflow, say so — the
fix is to stop importing the Dagster definitions eagerly, which is a change to
this repo's deployed entry point and needs a ruling, not a local workaround.

### Fetching the extractions — do this as yourself, not as a service

One route serves everything the profile can name:

    GET /ingest/{ingest_id}/extraction

The `ingest_id` is derivable from the document, so you never have to ask anyone
for it: it is `sha256:` followed by the sha256 of the document bytes, exactly as
minted by `doc_tools/utils/ingest_id.py`.

**Fetch under your own identity, as the dropper of the document.** The route is
dropper-scoped, and a service token is refused:

    403 {"error":"not_entitled",
         "message":"a service reads only the drops it seeded as a declared delegate"}

Measured against sandbox on 2026-10-31 with this repo's own `svc:doc-tools`
token. This is not an obstacle for you — you dropped your own notices, so you
may read their extractions — but it does mean **no cron, sensor or service
account can assemble the fixture for you.** A human with access runs this.

Save each response as JSON, one file per notice, unchanged. Do not hand-edit a
response: a fixture you corrected by hand scores your corrections.

## The private overlay layout

Keep your documents, your profile and your truth set in **one directory that is
not this repo and not a clone of it**:

    <private-root>/
      profiles/
        <your-profile>.yaml        # the column map: which columns, from which fields
      extractions/
        <one file per notice>.json # saved route responses, verbatim
      truth/
        <your-profile>.csv         # what you say the right answer is
      out/
        rows.csv                   # the fixture
        detail.csv                 # every disagreement, WITH values
        card.json                  # the scorecard

**Nothing enforces this layout.** Both commands take plain paths, and there is
no search path and no environment variable pointing at a profile directory. The
layout is a convention with one load-bearing rule: `out/` and `extractions/`
hold values, so the private root is never a git working tree. A repo ships the
*mechanism*; your box supplies the *case*.

The repo's own `registry/batch_profiles/pcn-ltb-by-part.yaml` is a worked,
validated profile. Copy it as a starting point. Its contract, column by column,
is [`docs/contracts/batch-column-map.md`](contracts/batch-column-map.md).

## Invocation

**Export.** The profile is validated before a single row is emitted, and the
output file is written only if every row came out clean. `PY` below is the
`.venv` interpreter from "Before you start", never a bare `python`:

    $PY -m doc_tools.batch.cli \
      --profile    <private-root>/profiles/<your-profile>.yaml \
      --extraction <private-root>/extractions \
      --out        <private-root>/out/rows.csv

`--extraction` takes a file or a directory of `*.json`, and repeats. Add
`--dry-run` to validate and report without writing, or `--fail-on-warning` to
treat a warning as fatal.

What it printed on the ten-notice run:

    note: 2 selected row(s) are inherited_doc_level (a doc-level value repeated
    onto a part) in column(s): LTB Date
    wrote 19 row(s)

That note is not noise. An `inherited_doc_level` value is a *document*-level
fact repeated onto a part row, so a column of part LTB dates can otherwise
quietly read as though every date were found per part.

**Score.** `--key` names the columns that identify a row, and repeats:

    $PY -m doc_tools.batch.score \
      --rows      <private-root>/out/rows.csv \
      --truth     <private-root>/truth/<your-profile>.csv \
      --profile   <private-root>/profiles/<your-profile>.yaml \
      --key "Notice" --key "Affected MPN" \
      --scorecard <private-root>/out/card.json \
      --detail    <private-root>/out/detail.csv

    warning: 1 truth row(s) not exported, 12 exported row(s) not in the truth set
    scored 7 joined row(s); totals.rate=0.7273

`--detail` is optional. Omit it and you get the numbers with no values written
anywhere. Add `--fail-under 0.95` to make a bad score a non-zero exit, for a
wrapper or a gate; without it a bad score still exits 0, because deciding what
is good enough is yours, not the tool's.

If two rows share a key the scorer refuses to guess which is which: exit 1,
nothing written, and the message names the remedy — declare a further `--key`.
The same affected MPN can legitimately appear twice on one notice.

## The truth-set format

A CSV whose header is the **output column names from your profile**, spelled
exactly. Any subset of them: you need the key columns and whichever columns you
actually want to check. A column the profile does not declare is an error, not a
warning, so a typo in a header cannot silently score nothing.

Three kinds of cell, and the difference is the whole point:

| Cell | Means |
| --- | --- |
| a value | the exported cell must equal this **byte for byte** |
| **empty** | asserts *nothing*; this cell is not scored |
| `<empty>` | asserts the exported cell **is** empty |

**A half-filled truth set is the normal case.** You are typing this by hand off
the notices; fill in what you have checked and leave the rest blank. Blank cells
cost you nothing and claim nothing. `<empty>` is how you say "there genuinely is
no replacement part here", which is a real finding and not a gap.

In a key column, `<empty>` also names the empty string, because a notice with no
parts exports one row with an empty part key.

The scorer **never normalises before comparing** — not case, not whitespace, not
date form. A scorer that normalises again hides the defect it exists to find.
`05/12/2023` is 5 December or 12 May depending on the vendor, and the exporter
deliberately refuses to guess; so when a date lands verbatim in `date_ambiguous`
that is the pipeline telling you it does not know, and your truth set should say
the mapped column is `<empty>` and the landing column holds the raw string.

A truth row that the export never produced is counted against you, not skipped.
That is the number that matters most: a rate over matched rows alone reads 100%
while a third of your notices never came out at all.

## What the scorecard shows

`card.json`, abridged from the ten-notice run:

    "rows":    {"exported": 19, "truth": 8, "joined": 7,
                "truth_only": 1, "exported_only": 12}
    "columns": {"Replacement MPN": {"asserted": 4, "match": 2, "mismatch": 1,
                                    "expected_empty_got_value": 0,
                                    "expected_value_got_empty": 0,
                                    "not_exported": 1, "rate": 0.5}, ...}
    "totals":  {"asserted": 11, "match": 8, "mismatch": 1,
                "expected_empty_got_value": 0, "expected_value_got_empty": 0,
                "not_exported": 2, "rate": 0.7272727272727273}

Read it like this.

- **`rows`** is the join, before any cell is compared. `truth_only` is rows you
  described that the export did not produce — the most serious number here.
  `exported_only` is rows you have not got round to describing, which is
  expected and is *not* counted against the score.
- **`columns`** is where the work is. Each column carries five buckets and they
  sum to `asserted`, so nothing is hidden between them:
  `match`, `mismatch`, `expected_empty_got_value` (you said there is nothing
  there, something came out), `expected_value_got_empty` (the pipeline missed
  it) and `not_exported` (the row never came out at all). A column whose misses
  are mostly `expected_value_got_empty` has a recall problem; mostly `mismatch`
  and it is reading the wrong thing.
- **`totals`** is the same five buckets summed. One rate definition everywhere:
  `rate` is always `match / asserted`, and `asserted` always includes the cells
  on rows that never came out.

`rate` is `null`, not `0`, when nothing was asserted — an empty truth set scores
nothing rather than scoring zero.

Exit codes: **0** scored, **1** a duplicated key or an unreadable input
(nothing written), **2** `--fail-under` was given and the rate is below it (the
scorecard is still written).

## What never leaves the box

Three of the four files in `out/` carry your values. One does not.

| File | Carries | May be shown |
| --- | --- | --- |
| `extractions/*.json` | the extracted values | **no** |
| `out/rows.csv` | the fixture itself | **no** |
| `out/detail.csv` | every disagreement, expected and got | **no** |
| `out/card.json` | integers, floats, your column names | **yes** |

The scorecard is safe **by construction, not by review**. Every string in it is
one of: a column name from your own profile, the profile name, or a fixed word
from a closed vocabulary. A test in this repo walks the emitted JSON and fails
if any other string appears, so it cannot drift into carrying a value. That is
why there are two files instead of one with a flag: a filter you have to
remember to apply is a filter that gets forgotten once.

`detail.csv` says so in its own first line, above the header, so a file opened
out of context still announces itself:

    # CONTAINS VALUES -- this file does not leave the box. The scorecard does.

Both commands keep to the same rule on stderr: diagnostics name line numbers,
counts, column names and error codes, never a cell value. So a transcript of a
run is shareable even though its outputs are not.

If you need a fixture that *can* be committed — a test case, not a measurement —
that is a different tool: `scripts/scrub_document.py`, which rewrites a document
into a synthetic one with a ledger. It is not part of this path, and it refuses
to emit a ledger it cannot prove, so do not reach for it to sanitise a
`rows.csv`.

## Measured

Run on 2026-10-31 against the ten-notice corpus standing in for a private set:
the real `ingest_id` of each of the ten, synthetic values.

- `wrote 19 row(s)`, exit 0, with the `inherited_doc_level` note above.
- scored against an 8-row half-filled truth set: `totals.rate=0.7273`, exit 0;
  `truth_only: 1`, one `mismatch`, two `not_exported` cells.
- the emitted `card.json` held no value, asserted by walking it.
- `52 passed in 18.03s` — `tests/test_batch_score.py`,
  `tests/test_batch_cli.py`, `tests/test_batch_profile.py`.

Against sandbox the same day: this repo's service token is refused by the
extraction route for all ten (`not_entitled`), five of the ten are not known to
cortex-bff at all (`ingest_not_found`), and `doc_tools/batch` is in **no**
deployed image — the batch tools run on an operator box by design, which is what
`v0.2.3` is for.

### 2026-11-03 — what is measured, and what the sandbox end-to-end still needs

Added with the import measurements in "Before you start" (36.2 s for
`--help`, 12.9 s for `import doc_tools` alone, both through this repo's venv).

**The toolchain half is measured end to end and needs nothing from the
cluster.** Export, score, scorecard and the no-value assertion all ran above on
saved responses, and neither command opens a socket.

**The sandbox half cannot be completed by this lane, and that is the design,
not a gap to close.** The one unmet prerequisite is item 2, a saved extraction,
and `GET /ingest/{id}/extraction` is dropper-scoped: it serves the identity that
seeded the drop and refuses every service token with `not_entitled`. So the
remaining step is *definitionally* the operator's — fetched under their own
identity, on their own box, for notices they dropped. No lane, cron, sensor or
Dagster asset can stand in, and no amount of work here changes that.

Two consequences worth stating plainly:

- **`doc_tools/batch` reaching a deployed image changes nothing about this.**
  The build is `COPY . /app` with no `.dockerignore`, so the module is in every
  image built since `0f19cf2`; the pinned image carries it. It is still the
  wrong place to run from, because the pod holds a *service* identity and that
  is the identity the route refuses.
- **The only end-to-end a service CAN run is a self-seeded one.** The 403 body
  says a service reads the drops it seeded as a declared delegate, so a
  synthetic notice dropped by this repo's own client could be read back and
  carried through export and score. That would exercise the chain without any
  human credential — but it writes a real drop into the cluster and mints real
  ingest state, so it is a decision to take deliberately and not a test to slip
  into a runbook verification.
