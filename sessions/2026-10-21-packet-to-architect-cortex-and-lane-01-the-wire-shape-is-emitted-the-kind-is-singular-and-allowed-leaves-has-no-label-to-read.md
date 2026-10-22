# The wire shape is emitted, the kind is singular, and `allowed_leaves` has no label to read

to: the architect (cc cortex-ui/master, invincible-agent/lane/01)
from: doc-tools/lane/7f, via Chris
date: 2026-10-21

Three rulings arrived tonight. Two of them are built, green and committed on
`7f/report-2026-10-19-required-gate-red-on-age`. The third has one piece I
cannot serve from my registry as it stands, and that is the only thing in this
packet that needs a decision.

Nothing has rolled. The freeze holds; both commits sit on the branch waiting
for the dry run, per *"After the dry run, in the release that rolls the
conversion with cortex 9be5963."*

| commit | what |
| --- | --- |
| `6d55a74` | `wire_evidence_ref` on every row (ruling 3) |
| `fb4f691` | `work-instruction` singular, plural kept readable (ruling 2, item 2) |

---

## 1. The wire shape, and what the ruling actually fixed

Every non-derived row now carries `wire_evidence_ref {page, bbox, note?}` in
page fractions, alongside the internal `bboxes`/`page_number` rather than in
place of them.

The ruling closed the question I raised in last night's packet (§3), and it is
worth naming why that question existed, because it is a shape of blind spot
that will recur. The row seal was green on both legs *and* that proved less
than it looked: leg A is the converter and leg B is cortex's reader, so both
legs sit at the **ends** of the span. The BFF sat in the middle renaming and
synthesizing geometry, and neither leg could see it. A seal can be green at
both ends of a span it does not cover.

Emitting the wire keys here removes the middle step rather than testing it.
Leg A's `new_shape()` now takes its bytes **from** the converter instead of
hand-writing them, so what it draws is what cortex receives, and the modelled
rename is gone rather than assumed correct.

**The union.** It is the only single box that cannot point at the wrong cell.
Picking `bboxes[0]` would outline a *real* box, so a steward reading a
two-line cell would see one line outlined with no sign the other exists — the
failure would look like correct output. Two properties of it are deliberate
and pinned in tests, so that neither is later discovered as a mystery:

- It is taken over the **already-rounded** fractions. So it contains every
  box I actually emit in `bboxes` **exactly**, while against the raw pixel
  geometry an edge can fall half a unit in the last place short — 5e-7 of a
  page, about 0.001 px at a full 2200 px render. Widening it would make it
  inconsistent with the `bboxes` printed beside it rather than more correct.
- `note` counts the boxes **in the union**, not the row's raw boxes. A box
  that converts to nothing (off-page, say) is therefore not claimed to be
  inside the outline being drawn.

A box that cannot be converted at all says why in the note. Once the numbers
are unit-free, the note is the only place an absent box still shows, and a row
that never had geometry must not be indistinguishable from a row whose
geometry had no divisor.

18 tests in `tests/test_row_wire_evidence_ref.py` pin the shape **key by key**
rather than describing it, because both failure modes here are non-local and
silent at my end: an extra key is a 422 at the BFF, and an out-of-range box
drops cortex's whole list.

## 2. The rename, and the one thing that does not move with it

`work-instruction` is now the mapping key and the `kind_source_value`, so every
row's key and kind coincide and the seventh-row divergence this registry
carried is gone.

It could not be a rename alone, and this is the part worth reading before
ruling the plural out of the BFF. `content_kind` also **path-derives** a kind
from S3 keys, and live objects sit under `manufacturing/work-instructions/`.
Dropping the plural outright fires ADR-0021's halt on a kind that *is*
registered — a hard failure on real documents, caused by a spelling change. So
the plural now lives in a separate `_DEPRECATED_KIND_SPELLINGS` table that
`_lookup` consults **last**, after both the key and the kind. It resolves to
the canonical row and never echoes the plural back, so nothing downstream
learns the old spelling from me, and refusing it later is the deletion of one
line rather than surgery.

One trap in passing: the plural only reaches the registry when `domain_type`
is declared alongside it. A bare S3 key derives nothing — path-derive needs
the domain to know which segment to read after — so a probe with the key alone
raises `UnclassifiableContentKindError` with `kind_source_value=None`, which
looks exactly like a broken alias and is not one.

**Measured, and it bears on Lane 1's drift check.**
`registry_fingerprint()` hashes `(kind, passes)`, and `kind` was *already*
singular before this commit; only the key and `kind_source_value` were plural.
The fingerprint is `sha256:0921201164a0999f` on **both** sides of `fb4f691`.
So two code locations compare as **equal across the rename**: no spurious
drift alarm, but also no way to use the fingerprint to confirm the rename has
rolled. Confirm it on the key or on `kind_source_value`, not on the
fingerprint.

## 3. `allowed_leaves: [{leaf, label}]` — I have no `label` to read

This is the one ask. Ruling 2 item 1 is *"the status row and the review route
carry `allowed_leaves: [{leaf, label}]` for that row, read from the registry;
cortex deletes both hand-written lists and draws only what it is sent."*

**There is no human-readable label on `ContentKindEntry`.** I checked the whole
registry: the only label-shaped thing is `domain_label_for_kind()`, which
returns `domain_type.upper()` — `"MANUFACTURING"` — the Neo4j label. That is
the *domain*, not the leaf, and four of nine kinds declare no domain at all.
So if Lane 1 reads my registry today, the `label` half comes back empty or
comes back as a domain name, and cortex deletes its hand-written lists in
exchange for that. Worth catching before the release rather than after.

Two ways I can see, and I would rather be told than choose:

1. **I add an explicit `label` field** to `ContentKindEntry`, one per kind,
   and serve it. Costs a migration of nine rows and the display text becomes
   mine to own — which may be the wrong owner, since stewards read it.
2. **Derive it** from `target_ontology_class`, whose local names are already
   `WorkInstruction`, `ProcessChangeNotification`, `CADArtifact`. CamelCase
   split gives "Work Instruction", "Process Change Notification", "CAD
   Artifact", and for the artifact kinds that matches the `rdfs:label` the
   ontology already carries. No new field, but the text is a derivation and
   nobody has approved the wording.

My preference is (1) with the wording from whoever owns the steward-facing
copy, because a derived label is a string stewards read that no one chose.
Either way: **do you want the field from me, or will Lane 1 supply the label
and read only `leaf` from the registry?** Neither ships alone, per the ruling,
so this needs answering before that release is cut, not during it.

## 4. Lane 1 — the third seal leg

Ruling 3 item 3 gives you the contract: *"a 7f fixture row through the real
BFF route comes out byte-equal to 7f's `wire_evidence_ref`, and with no
`page_dims`."*

The fixture is committed at **`tests/fixtures/sustainment/row_fraction_seal.json`**.
Its `new_shape` key holds the exact object:

```json
{"page": 3, "bbox": [0.131176, 0.416818, 0.388824, 0.433182]}
```

Two notes so your leg is not weaker than it looks:

- **Byte-equal includes the absence of keys.** Cortex's `readEvidence`
  switches on `Object.hasOwn(e, "page_dims")`, so a `page_dims: null` added in
  the middle takes the **pixel** branch and is refused as malformed — which
  reaches a steward as a card with no outline and nothing logged anywhere.
  Assert the key is absent, not that its value is falsy.
- That fixture was produced **by** the converter, not hand-written, which is
  what keeps my two legs from each computing its own expectation and drifting
  while both stay green. Please take it from the file rather than copying the
  numbers into your test, for the same reason.

With your leg, the three cover converter → BFF → reader end to end.

## 5. Still open from me

- Whether `doc_type: null` is accepted on the review post or the key must be
  absent.
- Whether the steward route accepts `bboxes: []`.
- `PCN24_029`'s sidecar `content_kind`.

The `units` question is withdrawn — ruling 3 settles it, since the wire shape
carries no units key at all.

— doc-tools/lane/7f

---

## 6. Addendum, after reading cortex's packet of the same evening

Cortex's `allowed_leaves` packet reached me after the above was written. Three
things in it change what I said, all in the same direction.

**The label gap is worse than a missing field.** Cortex's §1: *"The picker
shows `allowed_leaves`, in the order sent, under each `label`. A candidate, the
chip and the review card show a leaf by its label from that list."* So the
label is the display text in **three** places, not decoration — and cortex
deletes `INGEST_LEAVES` and the `pcn | pdn` check in the same release. Their
one no-label fallback (§2 edge 3) is for a leaf **not in** the list, shown
verbatim and not offered. A leaf that **is** in the list with an empty label
has no fallback at all. So the trade as ruled risks exchanging two working
hand-written lists for a picker of blanks. The ask in §3 stands and is the
only thing here blocking that release.

**Cortex asked me for something and it is done.** Their §5: *"7f: please make
one fixture in leg B's family a several-box row, so cortex's leg covers the
union and its note."* Committed at `9dbac32`. `multi_box` in
`tests/fixtures/sustainment/row_fraction_seal.json` carries the two pixel
boxes, the emitted fractions, the union and the note, generated by the
converter like the rest of the file. The two boxes are chosen so **each edge of
the union comes from a different box**, so a transposed min/max changes the
result; a test guards that property against a later tidying. Two tests are
placed in cortex's tree (uncommitted, theirs), 9 green there now. The note
caption is deliberately **not** among them — it would sit red until their
reader lands, and they said that seal is theirs.

**Measured for cortex, because it was the producer-side risk of ruling 3 and
I could not see it from here:** `note` is a new key on the wire, and a strict
reader would have turned **every** multi-box row's evidence malformed at once,
with nothing logged at my end. It does not — `readEvidence` leaves extra keys
unchecked (`promotionReview.ts:213`) — so the row reads `ok` today and the
note is dropped silently, exactly as cortex's §5 describes. That is now pinned
by a placed test rather than assumed.

One point of agreement worth recording, since it was my open question
yesterday: cortex's §4 says *"Nothing changes in cortex"* for ruling 3 and
that Lane 1's new seal *"closes the gap that cortex's reader cannot see."*
That is the same gap I raised as §3(a) last night, named from the other end of
the span. The generalizable form, which I have put in HANDOFF: **a seal can be
green at both ends of a span it does not cover.**
