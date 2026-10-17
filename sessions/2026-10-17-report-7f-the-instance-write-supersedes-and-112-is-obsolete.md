# Report: the instance write supersedes by DMC, and 112 is obsolete as the expected count

doc-tools/lane/7f, 2026-10-17 (Day 2 continued, after the `94f09a76` roll)

Ruling 2 is implemented and measured. One correction to a memory of my own
falls out of it, and it changes the number the re-ingest will be judged by.

## 1. Ruling 2, first half: the write is DMC-keyed and supersedes

Branch `7f/dmc-keyed-supersede`, commit `fd9aa85`, based on `main` (not
stacked, so the gate jobs actually dispatch).

The comment block on that write used to claim it was "set-idempotent on retry
BECAUSE the S1000D builder emits no timestamp, no uuid and no prov term". That
claim was true and too weak: it only ever meant *re-running the same bytes adds
nothing*. Once a module can be re-dropped with **new** bytes, idempotent has to
mean *the graph holds the current state of the module*, and a bare
`INSERT DATA` does not do that.

**The scope of the DELETE was measured before it was written**
(`scratchpad/dmc_supersede_predicate.py`, 6 MRAD modules, 36 subjects):

- Every subject is either `root_uri` or contains `-<slug>-`: **0 of 36
  uncovered**, across 9 shapes (`dmc-` plus the 8 scoped prefixes
  `part- tool- fig- faultcode- interval- item- step- proclist-`).
- **Both legs are required.** `root_uri` reads
  `mil:dmc-ODMRAD-A-34-10-01-00A-040A-A` while the slug reads
  `DMC-ODMRAD-A-34-10-01-00A-040A` — different case, no leading `DMC-`,
  trailing `-A`. The module's own subject does **not** match the slug test. I
  would have shipped a one-legged filter if I had reasoned about this instead
  of measuring it.
- **0 shared subjects and 0 shared triples** between modules, so the blast
  radius on a sibling is **0**. This is the *opposite* of the PCN side, where
  component IRIs are shared across notices and delete-by-subject is
  destructive. The rule does not transfer; it had to be re-measured here.
- **No dmRef target is ever a subject.** `s1000d_rdf.py:243` mints
  `dmc-<target>` in object position only, so this deletes nothing another
  module owns.

**Three things that are not obvious and are now pinned:**

- **One request, not two.** `DELETE` and `INSERT` ship in a single
  `application/sparql-update` body separated by `;`, which Fuseki applies in
  one transaction. Issued as two calls, a DELETE that commits followed by an
  INSERT that fails leaves the module with **no triples at all** — strictly
  worse than the duplication being fixed.
- **The key is the builder's `doc_slug`, not `doc_id`.** The slug is
  `_fragment(doc_id)`, so a filter written against the raw `doc_id` would
  silently match nothing for any `doc_id` carrying a sanitized character, and
  the write would stay additive with no error. Taken from the builder rather
  than re-derived, for the reason `_dmc_string_from_code` already states: same
  canonicalizer both sides, or the two never meet.
- **No `doc_slug` stays additive and warns.** iads/dita/40051 do not scope
  their subjects per document at all, so deleting by their subjects would take
  a sibling **document's** triples — the destructive case above. Unreachable
  today (only `s1000d-data-module` is routed), but it must not silently arm if
  one of them is wired up.

**Tests execute the body through rdflib rather than string-matching it:** a
re-drop with fewer steps takes v1 from 13 subjects to 5 and leaves **0
orphans**, with the graph at exactly v2's size; a sibling module keeps **30 of
30** triples across two supersedes of its neighbour; slug prefix collisions
pinned at **0**; an unsafe `root_uri` or slug refuses **before** any request.
`test_body_is_additive` is deliberately replaced. Suite: **1762 passed, 17
skipped, 7 deselected**.

## 2. Ruling 2, second half: the derivation, and 112 is obsolete

Asked for the expected count derived, not asserted. Derived
(`scratchpad/mrad_expected_count.py`), per module, over the six current files:

| module | triples |
|---|---|
| 040A | 5 |
| 320A | 11 |
| 421A | 12 |
| 520A | 30 |
| 720A | 40 |
| 941A | 49 |
| **sum** | **147** |

The modules share no triples (**0** duplicates lost to a union), and under the
supersede the graph holds exactly one version per module, so the expected count
**is** the sum.

**The reading, and what each outcome would mean:**

- **147** — the deployed bytes are the fixtures and the supersede worked.
- **146** — `image_prefix` was empty, which is a defect: production always
  passes `s3://{bucket}/{base_dir}/generated/{base_name}/images/`
  (`xml_ingestion.py:235`).
- **112, or 193** — a pre-#131 parser, or the additive accumulation.

**112 is obsolete and I should not have carried it forward.** It was derived
from the ten `urn:doc:` graphs as they stood on 10-13, which were written by a
**pre-#131** pin. #131 added the `rdf:List` procedure order with URI cells,
which adds triples to every procedural module — the same six fixtures went 99
to 146. Any expectation keyed on 112 is keyed on a parser that is no longer
deployed.

**A correction to my own memory, measured.** I had recorded "the deployed bytes
differ from the repo fixtures (941A 49 vs 48)". That difference is **an
`image_prefix` artifact, not a byte difference**: the builder emits `mil:hasURL`
only `if info_entity and self.image_prefix`, so 941A yields 48 with no prefix
and 49 with one. My fixture measurement had no prefix; production always has
one. Under production conditions the fixture is **also 49**. The slug scheme
does not change the count either way.

**What still stands:** the 720A and 520A pairs genuinely disagree (19 vs 14,
14 vs 9) and the +5 is not explained by `image_prefix`, so those are real byte
revisions. Which of the two is the "latest" per DMC is Lane 1's pick under the
ruling, and if the 10-09 bytes of those two modules are not the fixture bytes,
147 moves by their delta. **So 147 is the fixture-derived expectation**; the
authoritative derivation is the six deployed objects re-parsed at the pin that
carries the supersede, which is what the re-ingest itself does.

## 3. The sequencing consequence: this pin must roll BEFORE the re-ingest

`94f09a76` — live now, helm rev 50 — does **not** contain the supersede. If
Lane 1 writes the six retry rows against the current pin, the write is still
additive and the graph accumulates on top of whatever the 10-13 drops left.

Order: merge this, roll it, name the pin, **then** the six rows. The supersede
is self-healing for anything sharing a re-ingested module's `root_uri` or slug,
so no manual graph clear is needed — with one caveat I cannot settle from the
tree: if the two drops of a twice-dropped module carried **different
filenames**, their slugs differ and the older revision's scoped subjects
survive the supersede. That is checkable in one count once the re-ingest runs
(147 versus 147-plus-a-remainder), and it is cheaper to check then than to
probe for it now.

## 4. The 23 stale worktrees — Chris decides

Joined against PR state, because squash merges leave a branch tip out of
`main`'s ancestry and make bare ancestry a bad "did it land?" test. Dates are
last-commit.

**17 MERGED — safe to delete** (`git worktree remove`):

| date | branch | PR |
|---|---|---|
| 2026-09-25 | pcn/roll-600c454-report | #14 |
| 2026-09-27 | pcn/crop-four-edges | #22 |
| 2026-09-28 | lane/7f-header-trust | #24 |
| 2026-09-29 | pcn/corroboration-positive-evidence | #31 |
| 2026-09-30 | mesh/pin-sdk-v0.9.5 | #41 |
| 2026-09-30 | pcn/dotted-revision-order | #39 |
| 2026-09-30 | pcn/ltb-date-candidates | #32 |
| 2026-09-30 | pcn/pin-49ed4a1 | #42 |
| 2026-09-30 | pcn/tyc-header-ground-truth | #38 |
| 2026-09-30 | pcn/versioned-artifact-prefixes | #34 |
| 2026-10-02 | chore/gate-void-on-image-mismatch | #55 |
| 2026-10-02 | chore/kind-domain-optional | #58 |
| 2026-10-02 | chore/pin-sandbox-0c46fdb | #59 |
| 2026-10-02 | chore/pin-sandbox-78f8d10 | #57 |
| 2026-10-02 | chore/sor-placeholder | #60 |
| 2026-10-02 | feat/kind-registry-and-provenance-invariant | #56 |
| 2026-10-02 | mesh/ingress-user-stamp | #43 |

**Safe for a different reason — landed by squash, 0 unapplied patches:**

| date | branch | note |
|---|---|---|
| 2026-09-27 | pcn/prefer-text-layer | no PR, 2 commits ahead, `git cherry` says **0** unapplied |

**On a remote, so deleting the worktree loses nothing:**

| date | branch | state |
|---|---|---|
| 2026-09-17 | fix/sustainment-empty-crops | no PR, 1 unapplied, **pushed**, local ahead 0 |
| 2026-09-21 | mfg-extraction-investigation | no PR, **30** unapplied, **pushed**, local ahead 0 |
| 2026-09-28 | lane/7f-jena-ontology-writer | **PR #28 still OPEN** |
| 2026-10-05 | chore/pin-sandbox-877677c | **PR #73 still OPEN** |

**The one that is not safe to delete:**

| date | branch | why |
|---|---|---|
| 2026-10-02 | mesh/ingress-user-live-routes | 4 unapplied commits and **LOCAL ONLY** — not on origin, no PR. Deleting this worktree is the only one of the 23 that destroys work. |

Also: `C:/tmp/dt-grid` holds one **untracked** file,
`sessions/2026-09-26-report-7f-grid-forwarding-pr-17-open.md`, which exists
nowhere else. Worth rescuing before that worktree goes, even though its branch
(#22) is merged. No worktree has uncommitted changes to a **tracked** file.

**Recommendation:** delete the 17 merged plus `pcn/prefer-text-layer` (18),
after copying that one untracked report out of `dt-grid`. Push
`mesh/ingress-user-live-routes` first, or leave it. Leave #28 and #73 until
their PRs close.

## 5. Still owed

- **#28 and #73 remain open** from late September and early October.
  `mfg-extraction-investigation` carries **30** commits and has **no PR** at
  all — the largest unreviewed body of work in the repo.
- `mrad.ttl` regeneration in invincible-agent. Note it was generated with **no
  `image_prefix`**, so a regeneration under production conditions gives 147,
  not 146 — the contract and production disagree by exactly the one
  `mil:hasURL` triple, which is a decision for that repo rather than a drift
  to silently close.
- Rulings 1, 3, 4 and 5 are unblocked by the architect's answers and are the
  next pins; ruling 1 (stage posting with `s1000d-data-module` skipping the
  promotion filing) is the one Lane 1 is waiting on behind this roll.
