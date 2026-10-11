# 7f overnight — the nightly failed on a branch, and the illustration kind is not a kind

Order: the four-item OVERNIGHT dispatch. All four are answered below. Two of
them are answered with a **refusal to act plus the measurement that justifies
it**, which is the substance of this report; the other two shipped.

---

## 1. The 07:00Z gate read — the run exists, it FAILED, and it is not on main

**The nightly ran.** `docs/corpus-gate/report-2026-10-02T081312Z.md`,
`generated_at` `2026-10-02T08:13:12Z`, **verdict `fail`** — one blocking
condition. It is on **`origin/corpus-gate/nightly`** (tip `cddd6f9`,
*"chore(corpus-gate): nightly report, verdict fail"*) and **not on `main`**.

This is the publish-token limitation biting exactly where it was predicted to:
the token has contents write and no `pull_requests` write, so the nightly
commits its report to the branch and cannot open the PR that would land it.
The visible consequence is worse than a missing report:

> `main`'s `docs/corpus-gate/latest.json` says `"verdict": "pass"`
> (`generated_at` `2026-10-02T03:02:23Z`). The branch says `"verdict": "fail"`
> (`08:13:12Z`). **Anyone reading the authority on `main` right now reads a
> stale pass over a real fail.**

**The blocking condition** (report §"Identity-half unstable across fires"):

> `Diodes_PCN_2683_Rev1_EOL.pdf`: header fields disagree across fires and
> `needs_review` is not True in all three fires (undeclared silent write)

So this is the identity half, undeclared — not a known exemption. For contrast
the same run records `TYC-PCN-24-210412.pdf: header disagreement exempted —
needs_review=True in all three fires`, i.e. TYC took the **broad**
DISAGREEMENT exemption again, which is the narrowing that is still not on
`main`. Parts were clean: 9 scored, 0 errors, 1 of 9 `text_layer_degraded`.

### The guard was NOT tightened. Here is why that is the right answer.

The order's condition was *"`image_identity.checked == true` with a
pod-sourced match → tighten the guard; VOID is a finding."* Neither branch of
that fires:

| | value |
|---|---|
| `image_identity` (both main and branch) | **`null`** |
| `measured_image` (both) | `…@sha256:d881069b…` |
| active `image.digest` in `values-sandbox.yaml` on main | `…@sha256:b54d9ef2…` |

`image_identity: null` is **not a VOID verdict.** It is a report that predates
the field. The timeline settles it — all times local (CDT, UTC−5):

| when | what |
|---|---|
| 2026-10-01 22:02 | the `03:02Z` run (the one on `main`) |
| 2026-10-02 **03:13** | **the nightly run, `08:13Z`** |
| 2026-10-02 12:40 | `78f8d10` #55 — *a report that measured the wrong image is VOID* |
| 2026-10-02 16:42 | `7f22479` #57 — chart re-pin |
| 2026-10-02 18:13 | `c66dda3` #59 — chart re-pin again |
| 2026-10-02 **19:02** | **`06184c2` #61 — supply the gate's image expectation from a pod reading** |

Both existing reports were produced **9 to 16 hours before the code that emits
`image_identity` was merged.** The field cannot be present, so its absence
carries no information about the image. The same reasoning disposes of the
digest mismatch in the table above: `d881069b` ≠ `b54d9ef2` is not drift to
act on, because the chart was re-pinned twice and then rewritten by #61, all
*after* both runs measured. Each side of that comparison is stale with respect
to the other.

Tightening `tests/test_corpus_gate_guard.py` now would require the merged
reports to carry a block only a not-yet-deployed publisher can emit — the
precise trap where a required gate blocks the PR that improves it. **The
condition can first be met by a nightly that runs on an image built from ≥
`06184c2` with the chart pinned to that image.** Neither holds yet.

---

## 2. ICN on Figure nodes, hotspot_id on IPD items — SHIPPED

`c7672bf` on `feat/s1000d-week2-walk-seal`, pushed to PR #63. Covered in full
by `sessions/2026-10-02-report-7f-s1000d-week-2-the-walk-connects-and-the-seal-bites.md`
and its predecessor; the short version:

- `mil:hasICN` on the document-scoped Figure subject, from
  `graphic/@infoEntityIdent` **only** — never from `boardno`, which is a
  different identifier and had been conflated with it.
- `mil:hasHotspotId` on the IPD item, nested-in-item first, then joined to the
  figure's graphic by the item's key. A hotspot matching no item attaches to
  nothing.
- The bare-ICN-as-a-`hasURL` fallback is **deleted** — it emitted the literal
  `ICN-ODMRAD-00001` as a URL, the confabulation the 40051 parser already
  killed.
- The walk's parts row returns `icn` and `hotspot_id`, both as `OPTIONAL`. All
  three real rows bind `icn == ICN-ODMRAD-00001`; `hotspot_id` is asserted
  **unbound** on every row, because the authored corpus has no hotspots. That
  absence is a tracked assertion, not an xfail.
- Ground truth gained the measured ICN and `hotspot_id: null` with a note. No
  value was invented.
- The hotspot logic and the SVG join are sealed on a new, clearly-labelled
  `tests/fixtures/s1000d/hotspot/` fixture whose README states the markup is a
  session-authored, UNVERIFIED stand-in. The six corpus modules were not
  touched; the fixture is a sibling directory so it cannot match the corpus
  glob and silently move the count-based controls.

The order's *"stub until then"* was exactly the right call: the fixture corpus
has no `<hotspot>`, no `<itemSeqNumber>` (the key is `catalogSeqNumber/@item`),
and no SVG anywhere. All three were measured before any code was written.

---

## 3. #62 merged; `s1000d-data-module` already registered; the illustration kind is not registrable

### 3a. #62 merged — and the scrub is complete

Merged as `b473cc8` (CLEAN, MERGEABLE, checks green, plain `--squash`).

**A scrub-completeness claim I made earlier is retracted.** I ran a token diff
— names on removed lines that appear on no added line — and found one
capitalized proper noun still occurring 4 times across
`doc_tools/parsers/iads_extract.py` and `doc_tools/parsers/mil_40051_ingest.py`,
and reported the scrub as possibly incomplete. Re-measured against the right
refs:

| ref | files | occurrences |
|---|---|---|
| `b473cc8^` (pre-merge) | 2 | **4** |
| `b473cc8` (merged main) | 0 | **0** |

Those are the same two files and the same four occurrences — I had measured the
pre-merge tree. The substring count on merged `main` is zero. **The scrub is
complete; there is nothing to chase.** (The token was never printed in chat or
in this file.)

### 3b. `s1000d-data-module` needed no registration

It has been on the seam since #56/#54: `doc_tools/utils/content_kind.py:175`,
`target_ontology_class` `…mil#DataModule`, `domain_type` `maintenance`,
`passes=("s1000d.S1000dGraphBuilder",)`, `outputs=("mil:DataModule",)`. Nothing
to do.

### 3c. The illustration kind — NOT registered, and a row would have been wrong

Registering it would have been a false contract, for a reason better than "no
pass exists": **in this repo an illustration is a sidecar of a document drop,
never a drop.** The existing path, end to end:

1. an IADS package arrives and `assets/iads_ingestion.py` unpacks it;
2. `utils/cgm_convert.py` converts each CGM to PNG via LibreOffice headless and
   the asset uploads the result;
3. the extractor writes **`graphics_manifest.json`** beside the XML
   (`iads_ingestion.py:491`);
4. at XML-ingest time `assets/xml_ingestion.py:162` reads that manifest and
   hands it to the parser;
5. the parser resolves figure → URL **from the manifest only**.

A graphic is therefore never a drop object with its own content kind, and a
`kind="s1000d-illustration"` row would describe a thing the seam never
receives. The genuinely open question is architectural and not mine to guess:
**do OpenDDIL's SVGs arrive as a sidecar manifest beside the publication (reuse
step 3, no new kind at all), or as independent drop objects keyed by ICN (new
kind, plus a resolver pass that would have to be written)?** If the answer is
"sidecar", a content-kind row is not merely premature — it is wrong.

**And the live S1000D path is already confabulating the join the illustration
work exists to make real.** `xml_ingestion.py:199–205` passes
`graphics_manifest` to the **40051 parser only**:

```python
builder = PARSERS[doc_type](
    bucket=s3_bucket, doc_id=doc_id,
    image_prefix=image_prefix,
    graphics_manifest=graphics_manifest,
) if doc_type == "40051" else PARSERS[doc_type](
    bucket=s3_bucket, doc_id=doc_id, image_prefix=image_prefix,
)
```

S1000D gets only `image_prefix`, and `parsers/s1000d_rdf.py:327–329` then does:

```python
if info_entity and self.image_prefix:
    full_s3_url = f"{self.image_prefix}{info_entity}.png"
    self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
```

`image_prefix` is built unconditionally at `xml_ingestion.py:149`, so it is
**never empty on the live path**. Every S1000D figure therefore gets a
**predicted** `mil:hasURL` which may point at no object — the identical defect
the 40051 parser fixed with its CONFABULATION-KILL and a manifest requirement
(`mil_std_40051_rdf.py:240,297`). My commit removed the *bare-ICN* flavour of
this; the *predicted-path* flavour survives and is on the live path, not the
test path.

**I did not fix it, deliberately.** It changes live behaviour — figures would
lose their URL wherever no manifest exists — and it was not ordered. But it is
the real content of "register the illustration kind": the thing standing
between an ICN and an illustration is manifest wiring, not a registry row.
Recommended sequencing: decide sidecar-vs-drop; if sidecar, wire
`graphics_manifest` into `S1000dGraphBuilder` with the 40051
CONFABULATION-KILL rule and register **nothing**.

---

## 4. The 3xx content kind, proposed from the issue in use — SHIPPED

Written into group C of
`sessions/2026-10-02-packet-to-lane-1-mil-tbox-terms-the-s1000d-writer-emits-undeclared.md`,
replacing the previous unsourced ask. The source is the fixture corpus itself,
measured rather than recalled:

**The issue in use is S1000D Issue 4.2**, uniformly — all six modules declare
`…/S1000D_4-2/xml_schema_flat/<name>.xsd`. Per module:

| info code | schema | `infoName` | classifies as |
|---|---|---|---|
| 040 | `descript.xsd` | Description | `mil:DescriptiveDataModule` |
| **320** | **`schedul.xsd`** | **Maintenance Planning Data** | **the bare root** |
| 421 | `fault.xsd` | Fault Isolation | `mil:FaultIsolationDataModule` |
| 520 | `proced.xsd` | Remove Procedure | `mil:ProcedureDataModule` |
| 720 | `proced.xsd` | Install Procedure | `mil:ProcedureDataModule` |
| 941 | `ipd.xsd` | Illustrated Parts Data | `mil:IllustratedPartsDataModule` |

The declared schema agrees with the first-digit table's kind in **all five**
cases that classify, which is what licenses reading the sixth off its schema.
Two sourced candidate names are offered — `mil:ScheduledMaintenanceDataModule`
(from `schedul.xsd`, the structural contract) and
`mil:MaintenancePlanningDataModule` (from the authored `infoName`, free text) —
with a lean toward the schema name and the choice left to the owner.

**The caution is the real content of the ask.** `INFO_CODE_RANGES` keys on the
**first digit**, so a row for `"3"` assigns the kind to the whole 3xx family,
while the evidence covers **info code 320 only**. The `UNMAPPED_FAMILIES` gloss
calling 3xx *"maintenance-planning / scheduled-maintenance"* is now **sourced
for 320** and still **unsourced for the family** — nothing in this repo holds
the Issue 4.2 info-code table. So the packet asks for either sub-code
granularity (what today's evidence supports) or confirmation against that
table, which would also let the currently-unsourced `1xx` / `6xx` / `8xx`
glosses be sourced the same way. This is the ⚠ `mil_info_code_map.py`'s own
docstring raises, discharged as far as local data allows and no further.

---

## What a reader should do next

1. **Land the nightly's failing report on `main`** — a standing PR from
   `corpus-gate/nightly`, or grant the publish token `pull_requests: write`.
   Until then `latest.json` on `main` advertises a pass over a fail.
2. **Triage `Diodes_PCN_2683_Rev1_EOL.pdf`** — an undeclared identity-half
   disagreement, the one blocking condition.
3. **Answer sidecar-vs-drop for OpenDDIL graphics** (§3c). Everything about the
   illustration kind waits on that one sentence.
4. **Pick the 320 class name** (§4), then the map entry and the tightened
   reverse-hop assertion in the walk seal.
5. The gate guard tightening (§1) unblocks itself once a nightly runs on an
   image built from ≥ `06184c2` with the chart pinned to it.
