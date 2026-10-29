report: doc-tools/lane/7f, 2026-10-28
re: queue items 1 and 2 are ONE fire; the catalogue was stranded by a squash;
    and the standing "expect the next fire to go RED" prediction is superseded
status: fire in flight, two branches pushed, nothing waiting on anyone

No document value, filename or site identifier leaves this file. Digests are
printed; no secret is.

## 1. The pre-roll fire is up — the first one ever, against a cluster

`scripts/pcn_gate_prefire.py` had never been fired at sandbox. It has now.

| | |
|---|---|
| Job | `pcn-gate-preroll-01f016e430eb` |
| Pod | `pcn-gate-preroll-01f016e430eb-lscnf`, Running on `k3s-worker3` |
| Started | `2026-10-29T00:09:08Z` |
| Measures | `ghcr.io/edgy-solutions/doc-tools@sha256:01f016e430eb…` |
| Report lands on | `corpus-gate/preroll-01f016e430eb` |

Dry run first: all five overrides verified, the pod's `imageID` **corroborated
before** the GPU time, the clock checked (nightly ~7 h out), and no other gate
run contending for the single-model vision endpoint. Expect the report ~02:40Z.
No logs until it exits — a Job with no TTY logs nothing until then, by design.

**The candidate is `main` at `96d7b705`, proved from the bytes, not the tag.**
`:latest` → index `sha256:01f016e4…` → both children → config blob → label
`org.opencontainers.image.revision = 96d7b705689c`.

## 2. Queue items 1 and 2 are the same action, and this is why neither has measured

The deployed pin is `sha256:c056fa70…` = `38b7937` (#175, pinned 10-26). Measured
by ancestry, **it predates both #176 and `8ccda54`**:

    is #176 (b8a3dd0) in 38b7937?   no
    is #176 (b8a3dd0) in 96d7b705?  yes

So the per-field exemption fix (`8ccda54`, queue item 2) and the written-value
header arm (#176) are both **already in the tree and have never once run in a
deployed gate**. Item 2 needs no code; it needs this pin. The ruling's first two
queue items collapse into one fire, which is the one now in flight.

## 3. The export field catalogue was stranded by a squash merge — PR #182

#179 was **squash**-merged, so `git merge-base --is-ancestor` reports every one
of the 19 lane-branch commits as unmerged, and ancestry cannot tell which are
genuinely absent. Settled by **content** instead:

    git diff --stat origin/main 7f/gate-triggers-suspend-nightly
      registry/export_field_catalogue.json           | 1197 +
      sessions/…export-field-catalogue…md             |  282 +
      tests/fixtures/cortex_bff_extraction_pin.json  |  425 +
      tests/test_export_field_catalogue.py           |  430 +

**Four files, and nothing else.** Every other commit — `bd235fb`, `8ccda54`,
`51d7518`, `d625fa6` and the rest — is in main via the squash. So the only
stranded work was item 2's deliverable, sitting on a branch whose PR is already
closed. Cherry-picked onto `main` and opened as **PR #182**. The old lane branch
is now fully superseded and can be retired.

## 4. The standing "EXPECT THE NEXT FIRE TO GO RED" prediction is SUPERSEDED

The handoff carries a prediction, written against the 10-27 report, that the
next fire blocks on TYC-PCN-24-210412: it disagreed on
`doc_level_ltb_date_source` (`'06-JUN-2024' | '06-JUN-2024' | '-2024'`) and was
exempted by a `doc_id` reason, which the per-field rule would not accept.

**That prediction was written before #176 changed what the arm reads, and it no
longer holds.** Four links, each measured in the tree:

1. **The `-2024` reading was RAW, not written.** `pcn_header_agreement.py`'s
   default mode compares "exactly what the header LLM emitted, before any
   downstream trust logic touches it". The deployed gate predates #176, so that
   is the mode that produced the 10-27 line.
2. **The written mode does not compare `_source` at all.**
   `WRITTEN_FIELDS = ("doc_type", "mfr", "pub_date", "doc_level_ltb_date")` —
   no `_source` companion is in it. **The exact field the 10-27 report flagged
   is not measured under #176.**
3. **If the citation wobbles again, the value is refused, not written.** Run
   against the current tree:

       _date_components_consistent("2024-06-06", "06-JUN-2024") -> True
       _date_components_consistent("2024-06-06", "-2024")       -> False

   So `-2024` yields `source_is_a_different_date`, the witness is asked the same
   way and fails the same way, and `doc_level_ltb_date` is **blanked** with the
   reason `header.doc_level_ltb_date refused: '…' …` — the one-field declaration
   shape the gate matches, naming exactly the field that went blank.
4. **A blank in one fire is the blank-fire rule, not the all-three rule.**
   `apply_blank_fire_rule` requires the declaration **on the blank fire only**,
   and field-keyed: *"the blank fire is the one that wrote nothing while another
   fire had a value, so it is the only fire with something to declare."* Fire 3
   is both the blank fire and the declaring fire. **Exempted, correctly.**

**So TYC is not a predicted red on this fire.** Either all three fires cite the
date well and there is no disagreement, or fire 3 wobbles and the blank-fire
rule exempts it on a declaration about the right field. Neither path blocks.

**What does NOT change: it is still a silent recall loss.** An exempted TYC is a
notice that lost its LTB date in that fire. The exemption is honest about a
declared blank; it does not make the date present. That stays on the
reported-not-fixed list, where it already was.

**One real defect found on the way, not fixed, not blocking.**
`locate_header_source`'s docstring promises the rewritten `*_source` is *"always
the VERIFIED VALUE STRING, never the model's own snippet"* — and the `date`
branch returns `src`, the model's own snippet (`return True, "source_dates_value",
src`). That is why `06-JUN-2024` reaches the field at all. It is contained
(#176 stopped scoring the field), so it is a doc/code divergence rather than a
live wrong write, and it is **not** worth a pre-pin edit.

## 5. The pin branch is ready and holds for the report

`7f/pin-01f016e4`, one line of values moved, pushed, **no PR yet** — the report
is cherry-picked in first so the pin and its measurement land together.

- `image.digest` → `sha256:01f016e430eb…`. **`corpusGate.expectImage` deliberately
  NOT moved**: it is written in a second roll from the pod `imageID`, because
  copying the digest typed in above into it would make the gate compare the file
  against itself. Red by construction between the two rolls; both land clear of
  07:00Z.
- **The arm64 rule the file states was satisfied before the edit**, and recorded
  in the comment block: amd64 `9f80bb5b…`, arm64 `fb9183d8…`, both labelled
  revision `96d7b705689c`, built nine minutes apart — present and not stale.
- YAML re-parsed after the edit; no CRLF introduced (pinned files are written as
  bytes here, for the reason recorded in memory).

## 6. Next, in order

1. Report lands ~02:40Z → cherry-pick into `7f/pin-01f016e4` → PR → merge → roll.
2. **Read the pods' `imageID`** → write `expectImage` from that reading → roll
   again. Never by copying the digest just typed in.
3. #167 — deliberately **not** merged yet: a new `main` sha builds a new digest
   and would strand the measurement now in flight.
4. Then #180, then the batch chain, which is where the column-map vocabulary
   lives. **It is mine to write**, per the 10-28 ruling, and lane 01 has been
   told to release `policy/exports/` rather than wait on me.

— lane 7f
