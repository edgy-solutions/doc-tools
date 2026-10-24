# Report — `doc-tools/lane/7f`, 2026-10-23

**To the architect, via Chris.** Answers the directive: *"Freeze lifted. The split into topic PRs,
now, each rebased on main and each to Chris for review … Then one doc-tools release (v0.2.1) cut by
the new release job, pinned into Monday's 207. The doors-export drift: name the test to Lane 1 in a
packet so it's fixed before the roll, not after."*

## 1. The split: five PRs open, two branches held, one topic the list did not name

Every branch below is cut from `origin/main` and carries only the named commits, re-applied with a
pathspec of `doc_tools tests prompts scripts charts`. That pathspec is deliberate: it excludes
`sessions/` and `HANDOFF.md`, so the topic PRs are **code-only** and six of them cannot conflict
with each other on the handoff file. Each was run before its PR was opened.

| # | topic | PR | branch | from | tests |
|---|---|---|---|---|---|
| 1 | `detail=` on every failed post | **#147** | `7f/failed-post-carries-detail` | `12f5438` | 33 passed |
| 2 | ADI text-list salvage + review flags | **#148** | `7f/adi-text-list-salvage` | `9550736` | 21 passed |
| 3 | replacement precedence + grid prompt | **#149** | `7f/replacement-precedence-and-grid-prompt` | `e94c06b`, `fbc9932` | 82 passed |
| 6 | title read at the decision point | **#150** | `7f/leaf-at-the-decision-point` | `6bf8985`, `cd791ed`, `d9ad521`, `5c602c3`, `4661d54` | 131 passed |
| 7 | header bound + `doc_id` from the document | **#151** | `7f/header-bound-and-doc-id-from-the-document` | `da7c1ee`, `27add3e`, `80a7f30`, `3a59052` | 81 passed |
| 4 | evidence fractions + `wire_evidence_ref` | *held* | `7f/evidence-ref-page-fractions` | the conversion set | 155 passed |
| 5 | work-instruction singular + read-alias | *held* | `7f/work-instruction-singular` | `1ac8d40`, `fb4f691` | 82 passed |

**Topic 6's "(when ready)" inverts the real dependency, so 6 went first.** `doc_tools/utils/leaf_read.py`
is **created** by topic 6 (`cd791ed`) and then **modified** by topic 4 (`da03911`, `ee2422f`,
`d9e6118`) and topic 5 (`1ac8d40`). The order is forced: **6 → 4 → 5**. Measured, not assumed —
`1ac8d40` refused to apply on a topic-5 branch cut from `main` (`patch failed: leaf_read.py:86`),
and a `--3way` apply showed the comment block it patches is added by a topic-4 commit.

**So 4 and 5 are built, tested and pushed, but have no PR.** Not an omission: a PR stacked on
another branch **dispatches no CI at all** — not a failure, not a skip, no run record — so a
stacked review would have no verdict to show Chris. They are rebased onto `main` and opened the
moment #150 merges (then 4, then 5).

**#151 is a seventh topic the list does not name.** `da7c1ee`, `27add3e`, `80a7f30`, `3a59052` are
the 2026-10-20 header-identity ruling (items 1–3). They are code, they sit on the same branch as
everything else, and they belong to none of the six — a split into six would have **orphaned
them** on a branch about to be retired. If the intent was to hold that topic back, say so on #151
and it closes.

**Not in any topic PR: the ~25 report and HANDOFF commits** still on
`7f/report-2026-10-19-required-gate-red-on-age`, which is where this report lands too. Proposing
one docs-only PR last, after the code topics merge. Not opened without a word first.

## 2. The doors-export packet is placed

`invincible-agent/sessions/2026-10-23-packet-to-lane-01-from-7f-the-doors-export-passes-drift-is-one-overlay-line-and-ci-skips-the-test.md`
— **placed, not committed**, per the owning-lane rule.

It asks for one line, before the roll:
`policy/overlays/openddil-lab/content_kinds/doors-export.yaml:10`,
`identity.document_identity` → `identity.identity_from_doors_text`.

Checked before asking, so the packet is not a blind request:

- **It is exactly one line.** Of the four shared kinds, `engineering-document`, `pdf` and `xml` all
  agree on `passes` between our generated `registry/content_kinds/*.yaml` and their overlay.
  `doors-export` is the only row that drifts, and only on `passes` — `domain: null` is correct
  there and the `domain`/`outputs` assertions in the same test file are green.
- **The platform resolves neither symbol.** `src/iagent/content_kinds.py` never reads `passes`;
  `identity_from_doors_text` and `document_identity` exist nowhere in `invincible-agent/src`;
  `policy/content_kinds/` is a README-only seed. The SDK's `ContentKindRegistration.passes` is
  free-form `tuple[str, ...]` whose only validators are uniqueness and the branch-shape check — no
  symbol resolution, so a wrong name is not rejected and a corrected one is not resolved. The
  value is **documentary**, and their own header says it mirrors our generated file.
- **Ours is the scoped pass for a reason**, carried as a comment at
  `doc_tools/utils/content_kind.py:368-382`: `identity.document_identity` scans everything it is
  given for title-block labels, so a DOORS requirement whose **object text** reads `Contract No: …`
  would be read as the module's identity. Sealed by
  `tests/test_passes_dispatch.py::test_doors_object_text_contract_line_is_not_the_identity`.

**The red test, named:**
`tests/test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes`.

**And the trap worth keeping:** that test resolves the overlay from
`IAGENT_CONTENT_KIND_OVERLAY_DIR`, else the sibling checkout
`<repo>/../invincible-agent/policy/overlays`, and `pytest.skip`s when it can see neither. CI runs
`uv run -- python -m pytest -q -rs` in a single-repo checkout, so **it skips in CI and a green run
is no evidence the drift is fixed.** It is red only in a local full suite with both trees side by
side, which is how it was found and why it went to Lane 1 as a packet rather than as a CI failure
they would have seen. Every one of the five PR bodies says so, so a reviewer does not mistake it
for the PR's own breakage. If it should be *enforced* rather than skipped, that needs a job with
both trees; 7f will carry the doc-tools half on the word.

## 3. What is still owed on this directive

- **The v0.2.1 release** cut by the new release job, pinned into Monday's 207 — blocked on the
  topic PRs landing, and on **#146** (tag-from-digest) merging first, since cutting a release on
  the old `v*` trigger **rebuilds and overwrites both tags**.
- **Topics 4 and 5** opened as PRs, in that order, as #150 then #4 merge.
- **The docs PR** for the report/HANDOFF commits, on a word.

— `doc-tools/lane/7f`
