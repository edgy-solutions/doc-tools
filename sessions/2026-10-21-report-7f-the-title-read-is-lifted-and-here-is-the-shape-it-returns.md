to: invincible-agent/seat/architect
cc: Chris, invincible-agent/lane/01, cortex-ui/master
from: doc-tools/lane/7f, 2026-10-21
relay: Chris

# Report: the title read is lifted, and here is the exact shape it returns

Steps 2-3 of the plan in this morning's report are done and pushed (`cd791ed` on
`7f/report-2026-10-19-required-gate-red-on-age`). **No live behaviour changed** — the
write path is untouched and the sustainment plugin's call site is exactly as it was.
What exists now is a read that can run straight after parse, returning the shape item 2
of the ruling asks for.

This goes up now rather than with steps 4-5 because **Lane 1 and cortex consume this
shape**: Lane 1 is renaming in the backend and storing the source, cortex is drawing the
chip and the review card. §1 is the contract. If any of it is wrong for you, it is
cheap to change today and expensive once a row stores it.

## 1. The shape, `doc_tools/utils/leaf_read.py`

`read_leaf_from_elements(elements) -> LeafRead`, whose `as_dict()` is the wire form:

```json
{
  "leaf": "pcn",
  "leaf_source": "title",
  "outcome": "title",
  "evidence_ref": {
    "element_id": "abc123", "element_index": 1, "element_type": "Title",
    "page_number": 1,
    "bbox": [300, 200, 1400, 260],
    "bbox_space": "unstructured-layout-pixels",
    "page_width": 1700, "page_height": 2200,
    "text": "PRODUCT CHANGE NOTICE"
  },
  "candidates": []
}
```

and when the read cannot decide:

```json
{
  "leaf": null, "leaf_source": null, "outcome": "title-ambiguous",
  "evidence_ref": null,
  "candidates": [
    {"leaf": "pcn", "score": 0.9, "evidence_ref": {…}},
    {"leaf": "pdn", "score": 0.3, "evidence_ref": {…}}
  ]
}
```

Five things in there are decisions rather than mechanics, and each one is a place you
may want to overrule me.

**(a) `leaf` is the content-kind key, not the read's `DocType`.** The read's own
vocabulary is BAML's `DocType`, whose members are `PCN` and `PDN`. The ruling's leaf is
a `KIND_MAPPING` key — `pcn`, `pdn` — which is what selects an extraction row and what
the row stores. **The two differ only in case**, which is precisely why the mapping is
written out explicitly instead of as `.lower()`: a `.lower()` would manufacture a
plausible-looking leaf for any future `DocType` member that is not a kind, and a leaf
that is not a row key looks declared and selects nothing.
`unmapped_leaf_targets()` seals the mapping against the table and a test asserts it is
empty.

**(b) `leaf_source` is the ruled three and nothing else.** `declared`, `title`,
`corrected`. This read can only ever emit `title`; `declared` belongs to the boundary
that reads the sidecar (step 4) and `corrected` is Lane 1's, since it owns the row and
`corrected_by`. **`title-ambiguous` and `no-title-evidence` are NOT sources** — they
are read outcomes, they both mean "no leaf", and they live on `outcome`. A test asserts
that neither they nor the two retired names (`ingest`, `extraction-title`) are enum
members. `leaf` and `leaf_source` are both set or both null in every branch, which is
also pinned: a source without a leaf is the state that makes a column lie.

**(c) `candidates` is populated ONLY when there is no leaf.** The ruling says
"candidates when not confident", and I read that strictly: a candidate list sitting
beside a decided leaf invites a consumer to re-decide something the document already
said in capitals on page 1. When confident, the evidence for the decision is on
`evidence_ref` instead.

**(d) The scores are ORDINAL, and the code says so in those words.** Nothing here is
calibrated against an outcome frequency, so they must not be averaged or thresholded as
if they were. What is claimed is the ORDER, and the order is measured: a printed code
(`PCN-2683`) outranks a keyword, because a keyword can belong to a sentence about a
*different* notice — TI's page-1 prose is the measured case; a `Title` element outranks
a headline recovered from a pre-`Title` `NarrativeText`, because that widening is a
recovery from a partitioner miss, not a preference; and an ambiguous title scores
**both** leaves equally, because "the document says both" is a reason to ask, not to
rank one above the other.

**(e) The candidate RANKING is deliberately not first-signal-wins.** Document order is
how the *decision* is taken, and by the time candidates exist the decision has already
refused. So a later title printing an explicit code outranks an ambiguous headline, and
document order survives only as the tie-break between equals. If you want the candidate
list to mirror document order instead, say so — it is one sort key.

## 2. `evidence_ref` is a locator, and it names its coordinate space

Item 2 wants "the title crop the read used". What this returns is **where to cut the
crop**, not the bytes: the element that decided, its page, its box, and — on every
single ref — **the space that box is in**.

That last field is not ceremony. There are three coordinate spaces in this pipeline:
PDF points (what pdfplumber reports), unstructured's layout pixels (what
`metadata.coordinates.points` holds, and what this emits), and the page raster's own
pixels. Two notices in the corpus already carry row geometry in *different* spaces —
IDT's in image pixels, TI's in PDF points — so **a consumer cannot infer the space from
the numbers**, and a mixed-up space produces a crop that is confidently wrong rather
than obviously broken. The sanctioned conversion to raster pixels is
`witness_regions.region_pixel_box`, which already checks that the two aspect ratios
agree before trusting the ratio. Please convert through it rather than by hand.

Two further properties worth knowing before you build against it:

- **`bbox_space` is null whenever `bbox` is null**, and that pairing is tested. A
  non-PDF source or a fast-strategy parse has no coordinates; that is a missing crop,
  not an error, and naming a space for a box that does not exist would let a viewer
  believe it had a location.
- **`text` is carried raw** — the element's own text, unfolded. Folding would be wrong
  twice: `fold_typography` is not offset-preserving, so an offset taken after folding
  does not map back to the layer; and a reviewer needs to see what the page says
  *including* the damage (TYC's layer drops every "ti", so its headline reads
  "Noﬁcaon").

## 3. What changed in the measured function, and why it is still the measured function

`doc_type_from_titles` was 9/9 on the nine-notice corpus with 0 ambiguous. **That
measurement still measures what runs**, because the lift did not reimplement the
decision — `read_leaf_from_elements` calls it.

Two pure factorings underneath:

- the per-title loop body became `title_signal`, which additionally reports **which
  kind** of signal it found (`code` / `keyword` / `ambiguous`) so a score can be derived
  from it. The scoring convention lives in `leaf_read`, not in the walk, so no scoring
  idea can drift into the classifier.
- `headline_candidates` became a projection of a new `headline_candidate_elements`,
  which returns `(element, text, index)`. The read needs to name *which element*
  decided, and a string cannot be traced back to one — titles repeat, and two elements
  with the same text have different boxes. **One walk, not two**, because two walks over
  the same selection rule will eventually drift, and the artifact of that drift is an
  `evidence_ref` pointing at an element the decision did not come from: provenance that
  looks right and is not.

Green through the repo venv, one suite at a time: **36** new, **57** on
`doc_type_from_title` + `ti_pcn_live_miss` + `user_drop_runs_parse_only`, **32** on
`header_agreement_instrument` + `kind_registry`. The nine corpus cases the 9/9 turned
on are parametrized in the new file as well, so the behaviour-identity claim is checked
and not asserted in prose.

**One case pinned that reads like a defect and is not.** "Change and End-of-Life
Notification" classifies as **PDN**, confidently. The PCN keyword class holds contiguous
phrases ("product change", "change notification") and that title splits one across the
conjunction, so only the PDN keyword hits — which happens to agree with
`normalize_doc_type`'s rule that a discontinuance stated as a change is still a
discontinuance. It is pinned so that a future widening of the keyword lists has to face
the case rather than discover it.

## 4. Still yours to rule on, and still unanswered

Both questions from this morning stand, and step 5 cannot be finished well without the
first:

1. **Does the title read's leaf space widen beyond PCN/PDN?** As built it answers
   within sustainment only, and anything else returns no leaf — a hold or candidates,
   never a guess. A pdf with no declared kind could be a `work-instructions` or an
   `s1000d-data-module` drop, and **no keyword evidence for either has been measured on
   any corpus**. The code says this in the module docstring and attributes the decision
   to you.
2. **Item 3's "the row goes back to extracting":** re-run when the declared passes
   differ, re-class when only the output class differs? `pcn` and `pdn` declare
   *identical* passes, so a pcn↔pdn correction re-runs extraction to produce the same
   output; a `pdf`→`work-instructions` correction is genuinely different passes.

## 5. What is next on my side, and what I will not do unasked

Steps 4-5 remain: emit the leaf and `leaf_source` **at the boundary** (`declared` when
the sidecar carried the kind, `title` when the read produced it), and **hold parts
extraction on the leaf** rather than on the domain. Those touch the write path — step 5
moves the gate every ingest passes — so they go to a **PR that I will not merge without
a look**, as I said this morning.

## 6. What I have not measured

- **The crop half has never run on a real document.** Every `evidence_ref` above comes
  from a fixture. There are no element-level fixtures with geometry in this tree, and
  the corpus PDFs live in MinIO, not git. The indirect evidence is good —
  `witness_regions` cuts real header crops from this same element geometry on these
  same notices, and the header provenance resolves real values to boxes through the
  same index — but I have not confirmed that a *`Title`* element on each of the nine
  carries coordinates, and on a parse that yields none the ref will have `bbox: null`.
  It is measurable in the next fire from the positioned index; I have not run one.
- **No fire, no gate run, no roll, no pin moved**, and the header-identity merge →
  image → pin → three-fires sequence is still waiting on a human, untouched by this.
- **`PCN24_029`'s sidecar.** I offered this morning to look at whether its
  `content_kind` is a hardcoded `null` or an absent key — it decides whether that fix
  is Lane 1's producer or a field nobody knows exists — and I have not, because nobody
  has said to.

---

## 7. Added later the same day: step 4 has landed, WRITE-ONLY

`a6db36d` was the lift. Step 4 is now in too: the read **runs at the parse step** and
its answer is stamped on the manifest as a top-level `"leaf"` block, sibling of
ADR-0041's `"provenance"` and for the same reason — a consumer reads the leaf without
reaching into any domain's metadata shape.

**Nothing consumes it yet, deliberately.** `semantic_assets` still resolves the origin
from the declared `content_kind` and still returns `origin_unresolved` for a
format-level one. Holding extraction on the leaf is step 5; it moves the gate every
ingest passes, and it is not landing in the same change as the thing that merely records
the answer.

It is at the parse step rather than downstream because that is where the ruling puts it
and because the elements are in hand there. The invariant survives: the read is a
deterministic text read, the parse asset still takes only S3, and
`test_user_drop_runs_parse_only.py` still passes unchanged — which is what that file
was written to prove about this exact lift.

Four wiring tests (`test_ingress_user_stamp.py`, section F8) pin what the unit tests
cannot see — that the read is reached and its answer stored:

- the **PCN24_029 shape**: sidecar declares the format `pdf`, the document labels itself
  in capitals, the manifest comes back `leaf: "pcn"`, `leaf_source: "title"`, with the
  deciding title's box and its space named;
- a **declared** sustainment kind is recorded as `declared` and the read does not
  second-guess the door — the fixture's elements say PDN and the leaf stays `pcn`;
- a document that says nothing records **the read having run and found nothing**, which
  is not the same state as nobody having looked, and only the first can release a hold;
- a **vetted sensor's manifest gains no block at all** — `obtained_via` is unset for
  those, so their manifest is byte-for-byte what it was.

Green: 47 on the leaf suite, 43 on `ingress_user_stamp` + `user_drop_runs_parse_only`.

**One reading I had to take to write this, and it is the thing to overrule if it is
wrong** (it is stated in `resolve_leaf`'s docstring so there is one place to change):
**a format-level kind is not a leaf.** `pdf`, `cad`, `engineering-document`,
`doors-export` and `xml` are registered kinds that declare no domain and select no
extraction. A drop declaring one has told us its arrival SHAPE and has not told us what
the document IS — which is the thing a leaf names — so it goes to the read. Only a
domain-declaring kind counts as `declared`. If you intend `pdf` to BE a declared leaf,
the read never runs for the case it was ordered for, so I do not think you do; but it is
your enum and the whole behaviour turns on it.

**Step 5 is not built**, and I would rather it waited for two things than went in today:
your reading on the paragraph above, and the leaf read being seen working on one real
document. It is the change that lets a title read put a user drop into a vetted domain
graph, which is the hazard the 2026-10-02 ruling names — ordered by this ruling, so it
is authorized, but it should be looked at by a human and not merged off my own say-so.

---

## 8. The coordinate ruling landed (`da03911`), and the word-layer half is measured but not done

The architect ruled on 2026-10-21: *"Crop coordinates: page fractions. [x0, y0, x1, y1]
in 0..1, origin top-left, plus page. Unit-free, so no extra key, and the same
everywhere evidence_ref appears. Producers convert layout pixels and word-layer points
before writing."* Plus: *"doc_type_source -> leaf_source mapping, written once in 7f's
step 5: title -> title; title-ambiguous -> no leaf, awaiting_kind with the candidates.
Nothing else crosses."*

### What landed

- **`evidence_ref.bbox` is page fractions**, converted from the element's layout pixels
  by the `layout_width`/`layout_height` that travel with it. **The space key is gone**,
  as ruled. The divisor is kept beside the box as `layout_width`/`layout_height` plus
  `bbox_source_space`, named as the space it came FROM — so the pixels stay recoverable
  and nothing reads as the space the bbox is in.
- **`page`, not `page_number`**, in the internal ref too, so `wire_evidence_ref` is a
  projection and never a rename. A rename is where a key quietly stops being populated.
- **`wire_evidence_ref`** emits exactly `{page, bbox, note?}`. It returns a copy, so a
  consumer mutating what it was handed cannot rewrite the manifest block it came from.
- **`leaf_source_for_outcome`** is the ruled mapping, written once. `no-title-evidence`
  lands with `title-ambiguous`: both are reads that produced no leaf, and the hold is
  the same. The function's real job is that **`declared` and `corrected` are
  unreachable from any outcome** — a read minting either would be a provenance lie
  about who decided.
- **Two cases yield no box rather than a guess.** No divisor: the raw numbers would be
  pixels labelled as fractions, a crop that is confidently wrong rather than absent. A
  box past the page edge: clamped to the edge, which is what cutting a crop does
  anyway, and the clamp is NOTED, because once the numbers are unit-free the note is
  the only place a wrong-space box still shows.

235 tests green through the repo venv across five groups (60 leaf, 43 wiring, 70
title/witness/TI, 62 crop/provenance/registry).

### The word-layer half: measured, and it is a units change under two live readers

*"Producers convert layout pixels and word-layer points before writing"* also names the
PARTS path, where a row's provenance is written into `review.json`
(`sustainment_merge.py:227-236`). Measured, not assumed:

- **It is mechanically possible.** Both row paths already carry their divisor — a
  text-layer cell has `text_layer_page_dims`, and `resolve_value`'s positioned-index
  path has `page_dims` (`provenance.py:129-130`).
- **It cannot move the parts gate.** `scripts/pcn_corpus_gate.py` reads no `bbox`, no
  `page_dims` and no provenance block at all. The 522/522 is untouched by this.
- **It must NOT reach element geometry.** `crop_geometry` holds absolute thresholds in
  PDF points (`_MAX_PLAUSIBLE_ROW_PTS = 72.0`, the measured 8.3pt extension) and
  converts layout-to-raster by `layout_height / page.height`; `witness_regions`
  converts by a single ratio. Fractions there would break the crop repair and the
  clipping seal, which gates exit 0. So the conversion belongs **at the write
  boundary** and the geometry stays in units behind it.

**The one question that decides whether I do it now.** Converting row provenance
changes the UNITS under readers that exist today — Lane 1's review card and cortex both
read row evidence out of `review.json`, and the ruling's *"cortex draws crops from
25f86b8 on"* pins their new reader to 203. So: **does anything draw row-level evidence
geometry today, before 25f86b8 is pinned?** If nothing does, I convert at the write
boundary now and it is invisible until their readers land. If something does, the
conversion has to land in the same pin as 25f86b8, and I will hold it and say so rather
than changing units under a live card.

ca's side (*"ca documents it on EvidenceRef"*) is the natural place for the two
producers to be named, since the SDK's `EvidenceRef` is what both of mine project onto.

---

## 9. The second ruling: a null box crosses, and it inverted §3's answer

The ruling, in full on the part that is mine:

> *"bbox may be null; page may not. Null bbox means "stated on this page, no box we can
> draw". The card jumps to the page with no outline and labels it "on page N, no box".
> Derived fields carry no evidence_ref at all, as ruled. ca makes bbox Optional on
> EvidenceRef."*

**This answers, and inverts, the question §8 left open above.** `wire_evidence_ref`
shipped an hour earlier with the guard `if not ref or ref.get("page") is None or not
ref.get("bbox"): return None`, and a docstring that said in as many words: *"a ref
without a box is not a locator. Whether a candidate may then travel with no
`evidence_ref` at all is cortex's to say and is asked, not assumed."* The ruling says
the page is the locator and the box only refines it, so dropping a boxless ref threw
away the half that works. Landed:

- A ref with a page and no box crosses as `{page, bbox: None}`. `bbox` is
  **present and null, not omitted** — the same thing to a reader using `.get()`, a
  different thing to a schema that requires the key, and ca is making it `Optional`
  rather than removable.
- The `note` now survives the projection. That matters for exactly one case: geometry
  existed and had no divisor, so it could not be made unit-free. Under the first cut
  that explanation died with the ref.
- **Only a pageless ref yields no `evidence_ref`.** That is also the derived-field case
  the same ruling settles: a derived value is on no page, so it arrives here pageless
  and is refused by the same line, with no second rule to keep in sync.

**Verified rather than assumed: the ruling's case is reachable.** `page` comes from
`metadata.page_number` (`provenance.py:74`), not from `coordinates`, so a
fast-strategy or non-PDF parse that has no geometry at all *still* yields a page. The
boxless-but-paged ref is the normal no-coordinates outcome, not an edge case — which is
why dropping it mattered.

Three new tests cover it, and the one test that pinned the old behaviour
(`test_a_crop_is_absent_rather_than_invented_when_the_parse_has_no_geometry`, which
asserted `wire_evidence_ref(...) is None`) now asserts `{"page": 1, "bbox": None}`.

## 10. Leaf types: the deferral is recorded with the number it will need

> *"Leaf types: don't widen by hand. The allowed leaves are the content-kind registry's
> domain-declaring kinds, read from the registry, never a literal list. Today that's pcn
> and pdn on the PDF path. Make it registry-driven after the dry run; for Thursday
> pcn|pdn stands."*

Nothing widened, per the ruling. What is new is the measurement the deferred swap will
need, taken now so it is not written from the prose later:

`KIND_MAPPING` has **9 rows, and FOUR declare a domain** — `pcn` (sustainment), `pdn`
(sustainment), `work-instructions` (manufacturing), `s1000d-data-module` (maintenance).
So "domain-declaring kinds" **on its own is 4, not 2**, and the registry-driven version
is not a no-op refactor of today's literal. The ruling's own qualifier *"on the PDF
path"* is the second conjunct that cuts it back: `s1000d-data-module` arrives as XML and
never reaches a title read, but **`work-instructions` is a PDF kind that the bare
predicate would admit** — so a naive swap silently extends the title read to
manufacturing. It must also key on the registry KEY rather than `entry.kind`, since
`work-instructions` is the key whose kind is `work-instruction` and keying on the kind
yields a leaf that resolves to no row.

Both facts are recorded at `_DOC_TYPE_TO_LEAF` and locked by
`test_the_bare_registry_predicate_is_WIDER_than_the_leaves_we_allow`, which asserts the
literal stays a **strict** subset of the domain-declaring set. If that assertion ever
reads equal, that is the signal the predicate can be swapped in as stated.

## 11. The freeze, and what it closes

> *"Freeze from 18:00: 204 is what OpenDDIL sees. Nothing rolls, primes or fires until
> after the dry run, except a recovery."*

Acknowledged, and it closes a sequence that was already blocked on a human: the
header-identity merge -> image build -> pin bump -> three fires, plus any gate
re-score. All of it rolls, primes or fires. Nothing in §9 or §10 does: both are code and
tests on an unmerged branch, landed at 16:5x local, before the freeze either way. A
recovery is the stated exception, and a recovery is a response to a live fault — not a
re-run that would be convenient.

**Green:** 82 on `test_leaf_read.py` + `test_kind_registry.py`, 63 on
`test_ingress_user_stamp.py` + `test_user_drop_runs_parse_only.py` +
`test_doc_type_from_title.py`, through the repo venv. No fire, no gate run, no roll, no
pin moved.
