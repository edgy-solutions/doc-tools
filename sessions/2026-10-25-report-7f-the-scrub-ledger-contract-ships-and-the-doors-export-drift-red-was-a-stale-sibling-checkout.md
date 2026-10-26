to: architect, via Chris
from: doc-tools/lane/7f
date: 2026-10-25
re: overnight item 4 — the scrub ledger contract ships (PR to follow). Plus a
correction: yesterday's `doors-export` drift red was not a divergence.

## The order

> *4. Batch fixture: scrubber → schema PR, continue the chain.*

Done as the **contract**, not the scrubber. The design it implements is
`invincible-agent/sessions/2026-10-22-design-from-7f-batch-fixture-scrubber-for-chris-review.md`,
placed for Chris on 2026-10-22; §N below refers to it.

## 1. Why the schema could land with four rulings open

Design §5 asks four questions that are still unanswered. They block the
*tokeniser* — what gets scrubbed is exactly what they decide — but they do not
block the ledger, because the ledger has a required `policy` block that
**records** which answer a scrub ran under instead of choosing one:

| field | ruling | the example's recorded answer |
| --- | --- | --- |
| `manufacturer_name` | allowlisted or scrubbed? | `allowlisted` |
| `dates` | allowlisted? | `allowlisted` |
| `mapping` | may the mapping be kept in MinIO? | `one_way` |
| `enters_scored_corpus` | does a scrubbed fixture enter the SCORED corpus? | `false` |

`policy.authority` is required free text and the example's reads
`RECOMMENDATION ONLY -- 2026-10-22 design §5 rulings 1-4 are unanswered as of
2026-10-25`. A ruling that lands later invalidates exactly the fixtures whose
`policy` disagrees with it, **which is a query, not an audit**. Those four are
still the only thing standing between this and a real scrubber.

## 2. What the contract enforces

`doc_tools/scrub/ledger.py` — Pydantic models, `extra="forbid"`, `frozen=True`.
Each of these is a **rejection at load**, not a documented intention:

* **A raw original value cannot be stored.** `original` and `source.sha256` are
  typed `^len=(0|[1-9][0-9]*) sha256:[0-9a-f]{8}$`. The near misses are rejected
  too: a full 64-hex digest, a bare `len=18`, upper-case hex, nine hex digits, a
  leading-zero length.
* **A shape-unequal replacement is rejected.** Shape, not length — a
  right-length wrong-shape replacement makes the fixture measure the scrubber.
* **`occurrences` must equal `len(sites)`.** An uncounted occurrence is an
  unscrubbed one. A `table_cell` site must carry `row` and `col`.
* **The mapping is injective both ways**, and a replacement may not land on an
  allowlisted string (design §3.3 — the allowlist wins).
* **`policy.mapping` and `scrub.mapping_ref` must agree**, both directions. A
  one-way scrub naming a mapping either kept one or is lying about which.
* **`salt_ref` is a NAME.** A redaction pasted there is rejected, and so is
  anything that looks like raw entropy (16+ hex, or a base64-shaped blob).
* **All six verification checks must be present**, a `not_run` must say why, and
  `detail` cannot be empty on any result. `committable` is true only when every
  check PASSED, so a `refused` leak test — the text-layer-below-threshold case —
  **fails closed**.

`registry/scrub_ledger.schema.json` is **generated** from the models
(`scripts/generate_scrub_ledger_schema.py`, with `--check`, pinned by a test),
the same idiom as `registry/content_kinds/`. No `jsonschema` dependency added.
The generated file states its own limit in its `$comment`: *"Validating against
this file alone checks a ledger's shape, not its truth"* — the cross-field
invariants above live only in the model validators.

## 3. Four things found while building

1. **A truncated digest is weakly identifying, and the ledger's originals come
   from a catalogue.** `sha256:XXXXXXXX` is 32 bits; a few hundred thousand
   catalogue MPNs can be hashed and matched, and `len=N` in bytes narrows it
   further. The convention is repo policy and a longer digest only raises the
   cost of the same attack, so this is **accepted and written down**
   (`docs/contracts/scrub-ledger.md` §1.1) rather than glossed. Two consequences
   acted on: the example fixture's originals are entirely synthetic, so no
   digest of a real part is committed; and it is one more reason a **one-way**
   scrub (ruling 3) is the safer answer.
2. **The example is built through the model, and the model caught its author.**
   My hand-written customer-name replacement was eight letters against the
   original's nine and the shape-equality validator refused to build the file.
   Left in as a comment in `make_ledger_example.py`. A hand-written example
   would also have carried invented digests, so `covers()` would fail for every
   candidate and the file would teach a shape that does not round-trip.
3. **Design §7 says nothing in `doc_tools/` imports the scrubber, and a comment
   cannot enforce that**, so there is a source walk that fails on any import
   line mentioning `scrub` anywhere under `doc_tools/` outside `doc_tools/scrub/`.
   The module stays *inside* `doc_tools/` deliberately: `include = ["doc_tools*"]`
   is what CI installs, and a top-level `scrub/` would be importable in this tree
   and absent from the wheel — a drift between what the suite seals and what
   ships, which is worse than the import cost. The §7 guarantee is the guard, not
   the directory.

4. **CI caught a defect the local suite structurally could not, and it was mine.**
   The two `--check` staleness tests spawned `.venv/Scripts/python.exe`. That is
   the Windows layout; the runner has `.venv/bin/python`, so `FileNotFoundError`
   reddened the whole `tests` job while the same file is **28 passed** here. Fixed
   in `93185fb` to `sys.executable` — inside the suite the venv interpreter is
   already the one running, so the rule holds on both platforms and cannot drift
   from it. Worth stating because **`CLAUDE.md`'s "Python through this repo's venv
   only" rule is written as a literal Windows path**, and taking it literally in
   code that CI executes is a trap any lane can walk into. Every other
   `.venv\Scripts\python` in this tree is in a docstring telling a human how to
   run a generator, which is correct. `tests` is now **pass, 1m40s**.

## 4. CORRECTION: yesterday's `doors-export` drift red was not a divergence

Reported with PR #168 as *"the only red is the pre-existing #161 doors-export
overlay drift"*. Lane 01's packet today said the overlay on master already
carries both passes and asked where my `["identity.document_identity"]` came
from. Measured:

* `tests/test_overlay_kind_drift.py` reads the **sibling working tree** at
  `invincible-agent/policy/overlays/openddil-lab/content_kinds`, at no pinned ref.
* That shared checkout is on **another lane's branch**,
  `lane/ca-resolve-instance-adoption`, **91 commits behind `origin/master`**.
* `git show origin/master:policy/overlays/.../doors-export.yaml` declares
  `[identity.identity_from_doors_text, doors.requirements_rows]` — **which agrees
  with doc-tools `main`**.

Then measured rather than argued: `git archive origin/master` of that overlay
directory into a scratch dir, `IAGENT_CONTENT_KIND_OVERLAY_DIR` pointed at it,
and the seal runs **7 passed** — green on all ten shared kinds, `doors-export`
included.

So the seal was comparing this repo against a stale feature branch belonging to
a different lane. The #161 passes-*direction* ruling stands on its own; the red
was not evidence for it, and I should have checked the ref before reporting it.
Same lesson as "a local checkout is not the deployed contract", one repo over. I
have not pulled that tree — other lanes work in it.

This also clears PR #168: its one red was this same test, so there is no overlay
drift on either branch.

**Worth a ruling:** this seal should read a pinned ref (there is already a
`.github/doc-tools.ref` on the platform side doing the equivalent for the other
direction), or `IAGENT_CONTENT_KIND_OVERLAY_DIR` should be pointed at a pristine
export in CI. As it stands it reports whatever branch somebody left checked out.

## 5. Lane 01's MRAD packet: received, not started

`sessions/2026-10-25-packet-to-7f-from-lane-01-ask-the-manual-mrad-the-warning-is-not-extracted.md`
lands four `s1000d_rdf.py` extraction gaps on me, **the first a safety one**:
`reqSafety/warning/warningAndCautionPara` ("Disconnect power before removal.")
is not emitted at all, so the walk sends a mechanic to 520A with the procedure's
DMC and no warning. `mil_std_40051_rdf.py:190` and `iads_rdf.py:27` both emit
`mil:hasWarning`; `xml_chunks.py`'s `warning:N` branch already reads it, so one
emission would feed both stores. Then 421A's nested isolation tree, the dropped
support-equipment name, and 320A's planning paragraph.

Not started — item 4 was in flight. **My read: the warning gap outranks the three
header-gate fires** (item 3), which are in any case blocked twice over (below).
Asking for that ordering rather than assuming it.

## 6. Still blocked, unchanged

* **Item 3, three header-gate fires.** It is Sunday; 05:45Z–09:35Z is forbidden
  and Lane 1 rolls at 09:35Z. And PR #165 (the cancelled-header retry) must be
  merged *and* carried by a pin, or the fires do not test the fix.
* **Item 1 follow-through.** `scripts/neo4j_concept_id_migration.py` runs as a
  pod Job after #167 merges and a pin carries it; before/after counts go to tr.
* **Lane 01's 2026-10-23 packet** (`engineering-document`, a `schematic` kind,
  whether schematics need a domain) is still unanswered by me.

## 7. Files

| file | what |
| --- | --- |
| `doc_tools/scrub/ledger.py` | the models — the authority |
| `scripts/generate_scrub_ledger_schema.py` | projection generator, `--check` |
| `registry/scrub_ledger.schema.json` | generated |
| `tests/fixtures/scrub/make_ledger_example.py` | builds the example through the model, `--check` |
| `tests/fixtures/scrub/ledger_example.json` | a valid ledger, synthetic throughout |
| `tests/test_scrub_ledger.py` | 28 tests |
| `docs/contracts/scrub-ledger.md` | the contract, incl. §1.1 and the four rulings |
