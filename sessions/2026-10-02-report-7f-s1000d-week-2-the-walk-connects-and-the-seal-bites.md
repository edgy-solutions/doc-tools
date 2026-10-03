# 7f — S1000D week 2: the walk connects, and the seal bites

Date: 2026-10-02
Branch: `feat/s1000d-week2-walk-seal` (off `de7378d`)
Scope: the owed 2(e) work — fault-code nodes, `dmRef` edges, IPD items,
planning intervals, and the walk seal for `MRAD-ARR-0417` — plus the 07:00Z
gate read.

## The result

From the BIT code alone, SPARQL now gets to the part number:

    MRAD-ARR-0417  ->  421 (fault isolation)
                   ->  520 + 720 (procedures, by dmRef)
                   ->  941 (parts list, by dmRef from 720)
                   ->  ODM-AM-0001, quantity 1

`tests/test_s1000d_walk_seal.py`: **10/10**. The full local suite is 1174
passed, 29 skipped, with 3 pre-existing failures that are not mine (below).

All of it landed on the **wired** parser, `doc_tools/parsers/s1000d_rdf.py`.
`s1000d_ingest.py` is imported by no asset and is untouched.

## The seal is a measurement, because it was mutation-tested

It passed on the first run, which is the point at which a seal deserves less
trust rather than more. So I mutated the graph in the two ways the fix was meant
to prevent and required the queries to go silent:

| mutation | effect | detected by |
|---|---|---|
| the 5 `dmRef` targets re-joined by the pre-fix inline join | procedures 2 -> 0, walk 3 rows -> 0 | only the walk |
| the 6 `brexDmRef` elements harvested as content edges | refs 5 -> 11, self-loops 0 -> 6 | the two count controls |

The first mutation is the one worth noting: it leaves every label and the edge
**count** unchanged at 5. Nothing but an actual traversal can see it. That is
why the seal's strong unit test parses the referring module and the referenced
module with two separate builders and compares the target URI to the subject the
second one returns for itself — an inline join passes every label assertion and
fails that one.

Expectations come from `GROUND-TRUTH.json`, not from literals in the test, so
the seal cannot quietly agree with itself. I verified separately that all 15
ground-truth DMC citations normalize through the same canonicalizer to one of
the six assembled subjects; without that check a formatting difference between
two files would have read as a disagreement about the data.

## Two defects the work exposed, neither of them in the brief

**The `dmRef` XPath.** Of the 11 `<dmRef>` elements in the six-module corpus,
**six** are `identAndStatusSection/dmStatus/brexDmRef/dmRef`, and in this corpus
each names its OWN module's info code. An unfiltered `//dmRef` harvest emits six
self-loops and reports 11 cross-references where there are **5**. Excluded by
ancestor, with a negative control on both the count and the self-loops. This is
the same family as the earlier `grep '<dmRef'`-also-matches-`dmRefIdent` miscount
— the third time a dmRef count has been wrong for a containment reason.

**The module's own ident.** `//dmCode` also matches `dmRef/dmRefIdent/dmCode`.
It returns 2-4 elements per fixture file, and `[0]` was correct **only** because
`dmIdent` happens to precede `dmStatus` in document order. A document authoring
a `brexDmRef` first would have silently taken the wrong module's ident as its
own. Now a fallback chain preferring `//dmIdent/dmCode`, with a test that
authors the brex ref first.

Also fixed in passing, since IPD item identity depends on it: the `fig_{idx}`
figure fallback. The fixture's IPD `<figure>` has no `id`, so it coined
`fig-{scope}-fig_0` — a subject named after iteration order. Now
`@id` -> `graphic/@infoEntityIdent` -> loop index, the middle one being an
authored stable identifier.

## The handoff named a dead BIT code

The week-2 line said the seal runs "from `AM-BIT-017`". That code appears in
**no XML** — only in the scratch mock's `README.md`, `SPEC.md` and `RESULTS.md`
prose. The XML and `GROUND-TRUTH.json` both key `MRAD-ARR-0417`, which is what
the dispatch itself said. File mtimes put `RESULTS.md` about five hours before
the XML edits that renamed it, so those prose files are **stale, not false** —
but a seal written against the handoff's code would have queried a literal that
is not in the graph and read the empty result as a parser defect. Corrected in
`HANDOFF.md` with the reason attached, and recorded in the fixtures README so
the stale prose cannot re-introduce it.

## A finding for Lane 1 that came out of the probe

Info code **3xx has no `mil:*` content kind**, so the 320 maintenance-planning
module is typed only as the bare `mil:DataModule`. The classifier logs this
itself (that is `#53`'s fallthrough logging working), and 320 is the only
fallthrough in the corpus.

It matters more than it looks, because the planning interval is the one 2(e)
output that is **not** forward-reachable from a fault code: the 320 module names
the fault only in prose, so it coins no fault-code node. It is reached by asking
which module *refers to* the procedure the fault isolation cites — and with 320
untyped, that query cannot be narrowed by kind. So the seal asserts the reverse
hop **without** a kind constraint, which is strictly weaker than the forward
hops, which do constrain on `ProcedureDataModule` and
`IllustratedPartsDataModule`. Give 3xx a kind and that one assertion tightens.

Packet: `sessions/2026-10-02-packet-to-lane-1-mil-tbox-terms-the-s1000d-writer-emits-undeclared.md`.
It carries three groups — and group A is **not** from this week: `mil:Figure`,
`mil:hasFigure`, `mil:hasPartNumber` and `mil:hasURL` are already written by
this parser and declared in **no** TTL (0 occurrences each across all 17 files
in `setup/ontologies/`). I flagged that explicitly so group B is not mistaken
for the cause. Nothing here is blocking: the graphs are served without
reasoning, so a query naming the predicate still matches; what an undeclared
class cannot do is participate in subclass routing, and I have not measured a
specific consumer failing on it.

## The gate read: nothing to read

`docs/corpus-gate/latest.json` on `origin/main` is still the
**2026-10-02T03:02:23Z** report, `verdict: pass`, `measured_image` `d881069b`,
**`image_identity: null`**. No run has landed since the expectation went live at
revision 31. The first run that can satisfy the held tightening is
**2026-10-03 07:00Z**, so the guard stays as it is. Checked the report rather
than inferring from the chart or the date.

## The three local failures are not mine

`tests/test_mesh_sdk_pin.py` fails 3 tests on `ModuleNotFoundError`. The local
venv has `iagent-mesh` **0.9.4** installed while `pyproject.toml` pins
**v0.9.5**, and `provenance.py` only exists from 0.9.5 — the known floor. Those
tests contain zero references to S1000D. CI installs from the pin.

## Open

- **The fixtures' ground truth is a DRAFT** with two open questions of its own:
  whether `remove_install` should be a list or the single DMC the consumer's
  shape expects, and whether option 4 should cite 320 for the interval.
  Incidentally relevant to the second: `option4` cites 421/520/720/941 and
  **not** 320, so the reverse hop is the only route by which an answer could
  cite the interval module at all.
- **Still owed from the same dispatch:** register the S1000D kind on the ingest
  seam and run the ordinary `/ingest`. No throwaway target, no `synthetic`
  flag; the seam carries the MinIO credentials. Not started.
- **Still unclaimed:** no `urn:doc:*` named graph exists in sandbox Jena, so
  S1000D remains unproven end-to-end. `iads_rdf.py`, `dita_rdf.py` and
  `mil_std_40051_rdf.py` share the unscoped-subject defect this parser no
  longer has.
