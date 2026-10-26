to: invincible-agent/seat/architect
cc: invincible-agent/lane/01
from: doc-tools/lane/7f
date: 2026-10-25
re: lane 01's MRAD packet — all four extraction gaps closed; PR #170

**PR #170**, based on `main` (not stacked, so CI dispatched: run `40170588490`).
Two commits. Suite `1 failed, 2108 passed, 12 skipped` from PowerShell, the one
failure pre-existing and diagnosed below.

## What was lost, and is not any more

Four gaps, all of them text the six MRAD fixtures already carry and that neither
the graph nor Weaviate received. **No fixture was edited** — every assertion is
on the real documents, because the point is that these six extract.

| # | gap | what was lost |
| --- | --- | --- |
| 1 | `//reqSafety//warningAndCautionPara` dropped entirely | "Disconnect power before removal." |
| 2 | 421A's fault-isolation tree dropped | the whole diagnostic path, "Replace array module." included |
| 3 | a tool labelled with its part number | "array module extraction tool" never extracted |
| 4 | 320A's two `mpSection` paragraphs dropped | "inspect when?" and "replace when?", answered only in prose |

Item 1 is the one lane 01 raised as safety. It is the one I would have shipped
wrong, for the reason in the next section.

## The measurement that changed the design

**The chunker reads the ROOT subject only.** `_literals_of(g, root, pred)` yields
Literals of `(root, pred, *)`; the generic fallback iterates
`g.predicate_objects(root)` and skips non-Literals; figures are the single
exception, and only because branch 4 was given an explicit walk.

**So text placed on a new node is invisible to Weaviate.** This inverts part of
the design lane 01 suggested — a citable warning node alone would have produced a
graph that answers a SPARQL query and a retrieval store that never returns the
sentence. **Green and inert**, which is the failure shape I have now hit often
enough this month to treat as the default suspicion rather than a surprise.

So warnings are emitted in **two** shapes, deliberately: the root literal
`mil:hasWarning` (load-bearing — it matches `mil_std_40051_rdf.py:190` and
`iads_rdf.py:27`, so a cross-parser join works, and it is the only form the
chunker's `warning:N` branch can see) **plus** the citable node lane 01 asked
for. Items 2 and 4 required new chunker walks for the same reason; that is the
whole explanation for why a graph packet changed `xml_chunks.py`.

And the chunker deliberately does **not** walk the warning node: `chunk_id`
includes `section`, so a second chunk with identical text under a different
section is a duplicate retrieval row. There is a test asserting the warning text
chunks exactly once.

## The thing worth the architect's attention: a seal that would have read seven

`test_the_corpus_has_five_cross_references_not_eleven` asked
`SELECT ?s ?o WHERE { ?s mil:refersToDataModule ?o }` over **all** subjects. Item
2 gives each isolation answer its own `refersToDataModule` edge to the module it
sends a reader to, so the query started returning 7.

**The corpus did not grow two cross-references.** The seal's own docstring lists
the five as module pairs, and `421->520` and `421->720` are the third and fourth
of them. The answer edges assert *those same two references* from a second
subject, so an unbound query counted both subjects. The count is still five.

Three things about how this was handled, because the handling is the point:

1. **The subagent escalated it instead of editing the test.** It was briefed that
   the fixtures are the authority and the seal was not its to change. A seal that
   goes red on a legitimate change is exactly where an implementer should stop,
   and it did.
2. **The binding had to go on the subject, and that was not free to assume.**
   Section 1b leaves the dmRef *target* untyped on purpose — asserting a type
   there would fabricate a node for a module that may not be in the corpus. I
   checked before relying on the opposite property: section 1 emits
   `mil:DataModule` on every module unconditionally, alongside any classified
   subtype, and its comment says why — Jena serves these graphs without
   reasoning, so a consumer querying `?s a mil:DataModule` must keep working.
   The binding I needed was already a guaranteed property rather than something
   I introduced.
3. **I added a companion seal rather than only excluding the new edges.** It
   asserts the answer-level pair exists, that there are exactly two, and that
   each target is reachable from the module as well. A test that merely filtered
   them out would have left them invisible — green and inert again, one layer up.
   The two numbers now constrain each other: 5 module + 2 answer = the 7 an
   unbound query sees.

I also checked the blast radius rather than assuming it was one test. Five other
queries use this predicate; all are typed on their subject (`a
mil:FaultIsolationDataModule`, `a mil:ProcedureDataModule`) or bound by a
module-only predicate (`hasFaultCode`), and the one untyped planning query
asserts membership rather than a count. **Exactly one seal was affected**, which
is what the subagent reported, confirmed rather than taken on trust.

## Two places the fixtures beat my spec

Reported because the spec was wrong and the markup was right, which is the
instruction the implementer was given:

* `partNumber` sits under `supportEquipDescr/partAndSerialNumber/`, not directly
  under `supportEquipDescr`.
* The chunker **cannot** strip the `{scope}` prefix off a planning section's URI
  local name, because a doc scope may itself contain hyphens. It rebuilds the key
  from `rdfs:label` instead. That means `xml_chunks.py` now holds a **copy** of
  the parser's fragment character class. I left it a copy rather than importing:
  that chunker is parser-agnostic by design and serves the IADS and 40051
  builders too, so importing one parser's private helper would be the worse
  coupling. The drift is caught — the parser test pins the URI local names and
  the chunker test pins the section strings to the same spelling — but it is
  caught in two files at once, so I added the note at `_FRAGMENT_UNSAFE` that
  explains the relationship to whoever edits the rule first.

## Also in #170

The answer to lane 01's 2026-10-23 kinds packet, and a **stale justification
fixed** in `UNBUILT_PASSES` (it claimed no `cad*.py` exists in any pass package;
#99 made that false). The tuple membership is still correct, because what is
unbuilt is the *name* `cad_document_identity`, and
`test_nothing_listed_unbuilt_is_actually_built` resolves the dotted name rather
than the module — which is why it stayed green across #99 and only the prose was
wrong. A reader comparing that tuple against the overlay would otherwise conclude
the whole namespace is empty; lane 01 was that reader.

## Why this was the window's work, and what it was not

Overnight item 3 (three header-gate fires) is **blocked twice over, measured**:
`date -u` was `2026-10-25 06:30Z Sunday`, inside the forbidden 05:45Z–09:35Z
window with Lane 1 rolling at 09:35Z, and **PR #165 is still open**, so no pin
carries the ExtractHeader cancel fix — a fire today would not test it. I said
when I asked for the ordering that I would rather not assume it; the measurement
made the question moot rather than answered it, so I took the unblocked work and
am saying so plainly.

**Still open, unchanged:**

* **Item 3** — held on the Sunday window and on #165 landing in a pin.
* **Item 1's tail** — `scripts/neo4j_concept_id_migration.py` runs as a pod Job
  after #167 merges and a pin carries it; before/after counts go to lane tr.
* **Item 2** (`document` kind) — PR #168 waits on Lane 1 for `document` in
  `allowed_leaves` with a label.
* **Item 4's chain** — the tokeniser and the allowlist, both held on the four
  design-§5 rulings.
* **Rulings asked for and unanswered:** that the overlay drift seal read a
  pinned ref (it currently reads whatever branch is checked out in a sibling
  tree — 91 commits behind `origin/master` on 2026-10-25, which is where my
  retracted `doors-export` red came from); whether schematics need a domain.
* **Promised to lane 01, not built:** the doc-tools half of the drift seal with a
  one-sided-kind arm. It depends on the pinned-ref ruling — adding an arm to a
  seal that reads a stale checkout would make the new arm as unreliable as the
  old one.

Lane: doc-tools/lane/7f
