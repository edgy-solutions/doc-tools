# The MRAD six-module S1000D mock

Six hand-authored S1000D data modules for one fictional system (model ident
code `ODMRAD`, a phased-array radar), plus `GROUND-TRUTH.json`. They exist so
the S1000D parser can be scored on a **multi-module corpus** rather than on a
single module, because the behaviours that matter most — cross-module
references, subject collisions between documents, and whether a walk can get
from a symptom to a part number — are invisible in a one-module test.

| info code | module | what it carries |
|---|---|---|
| 040 | descriptive | general description |
| 320 | maintenance planning | an on-condition task and a **180 day** interval |
| 421 | fault isolation | fault code **`MRAD-ARR-0417`** and the isolation tree |
| 520 | procedure | remove |
| 720 | procedure | install, and a `reqSpares` part |
| 941 | illustrated parts | the figure and three catalog items |

## What they were authored to exercise

The intended walk, which `tests/test_s1000d_walk_seal.py` executes in SPARQL:

    MRAD-ARR-0417  ->  421 (fault isolation)
                   ->  520 + 720 (the procedures, by dmRef)
                   ->  941 (the parts list, by dmRef from 720)
                   ->  ODM-AM-0001, quantity 1

## Three things to know before using these

**`GROUND-TRUTH.json` is a DRAFT.** Its own `status` field says so, and it
carries two `open_questions` — whether `remove_install` should be a list or the
single DMC the consumer's shape expects, and whether option 4 should cite 320
for the interval at all. Do not treat an answer it does not settle as settled.

**The fault code is `MRAD-ARR-0417`.** An earlier draft called it
`AM-BIT-017`, and that name survives in the scratch mock's `README.md`,
`SPEC.md` and `RESULTS.md`, which were written before the rename and are **not
copied here**. Those files' measurements predate the rename (file mtimes put
`RESULTS.md` ~5h before the XML edits), so they are stale rather than false. A
seal written against `AM-BIT-017` queries a literal that is in no XML and reads
the empty result as a parser defect.

**Some element names are plausible stand-ins, not verified schema.** The XML
says so inline in two places: the 320 module's
`scheduling/mpSystem/mpSystemChap/mpSection` nesting, and the 421 module's
fault elements. The author was not certain of `schedul.xsd` or the 4.2 fault
schema's exact spellings. That is fine for scoring the parser's *graph shape*
— it is not evidence about real S1000D documents, and a parser change
justified only by these fixtures is unproven on real data.

Six of the 11 `<dmRef>` elements in this set are
`identAndStatusSection/dmStatus/brexDmRef/dmRef`, and each points at its own
module's info code. A naive `//dmRef` harvest therefore emits six self-loops
and reports 11 cross-references where there are **5**. The parser excludes them
by ancestor; `test_s1000d_walk_seal.py` keeps a negative control on both counts.

Source: `C:\tmp\overnight-1002\M6` (scratch). The XML and `GROUND-TRUTH.json`
here are byte-identical copies, verified by sha256 at copy time.
