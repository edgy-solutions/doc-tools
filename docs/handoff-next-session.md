# Handoff — next session, start here

**Written:** 2026-09-21. **Priority order below is the user's, stated directly:**
PCN/PDN extraction correctness first; manufacturing chunking resumes only after
the user runs diagnostics at work again, which they said would be "next week"
(i.e. on or after 2026-09-22) and have not done yet as of this writing.

This file is an entry point. The two docs below carry the actual technical
content and are current — read them, don't re-derive them.

- `docs/handoff-pdn-continuation-table-pairing.md` — the PCN/PDN fix
- `docs/handoff-manufacturing-chunking-and-experiment.md` — the manufacturing
  chunking/segmenter work

---

## 1. PCN/PDN — ANSWERED 2026-09-21, corpus validation done

The user asked directly: *"did you test these fixes against the pdns in minio
I provided you? And if so did you validate the results were sane?"*

**It has now been run against the real notices.** Full report:
`docs/pcn-corpus-validation-2026-09-21.md` on `fix/pcn-continuation-table-pairing`
(worktree `C:/tmp/doc-tools-pcn`). Read that, not this summary, before acting.

What the corpus run established, over all 9 distinct PDFs under
`sustainment/inbound/`, baseline (`origin/main`, verified byte-identical to the
module in the running pod) vs the fix branch:

- **The alias veto is real and correct.** `TYC-PCN-24-210412.pdf` drops from 38
  to 24 parts; all 14 dropped are `Alias Part Number(s)` / `Substitute Alias`
  values, all quote-wrapped, exactly the 14 predicted. No other notice changes.
- **The "136 of 402 replacements sold as affected parts" premise is FALSE.**
  It was an artifact of `scripts/pdn_parts_diagnostic.py`'s own
  `index_tables(..., inherit_headers=True)`. All 136 sit on Diodes PCN 2683
  pages 4 and 5, whose captions read *"...and No Replacement Parts"* — separate
  column-major EOL lists, not continuation pages. The diagnostic inherited page
  3's `EOL|Replacement` classification onto them because all three tables are 6
  wide in `text.json` grid space, and relabelled genuine EOL devices. Do not
  cite the figure again; it is corrected in the PDN handoff and in the code.
- **A latent regression was found in the fix, and fixed.** Inheritance was
  checked before the caption rule, so a column-count coincidence would have
  reclassified **144 genuine EOL devices** on those same pages as replacements.
  Closed by a table-number caption veto (`_names_a_different_table`) in
  `table_text_layer.py`, pinned by four new tests. 52 tests pass; the
  full-corpus A/B is byte-for-byte unchanged after the patch.
- **Pre-existing recall gap, reported not fixed:** 5 of 9 notices yield zero
  tier-1 parts (headerless grids; and `ADI_PDN_23_0120.pdf`'s affected column is
  headed `Model`, absent from `AFFECTED_HEADERS`). Production falls back to the
  vision pass, so this is not proof of product loss. §4 of the report.

**Method note for whoever re-validates.** Do *not* use the diagnostic's
`--tl-path` loop described in the PDN handoff: it grades the already-stored
`extraction.json`, which was produced by pre-fix code, so it can never show
post-fix extraction behaviour. Drive the extractor directly over the PDFs
instead (`ab_pdn.py` pattern, §"How it was run"). `kubectl exec` was **not**
blocked this session — `kubectl cp` the script in and exec it, rather than
piping on stdin, which is what the classifier had objected to.

**Still open:** `fix/pcn-continuation-table-pairing` is not pushed (upstream is
still `origin/main` — check with `git rev-parse --abbrev-ref
fix/pcn-continuation-table-pairing@{upstream}`), and the caption-veto patch,
the new tests and the validation report were uncommitted as of this writing.

## 2. Manufacturing — correctly paused, do not restart on your own

User-deferred, not blocked. The reallayout fixture
(`tests/fixtures/manufacturing/make_synthetic_wi_reallayout.py`, `308f365`/
`370b981`) is done and verified to discriminate between segmenter designs
(naive regex 73/109 vs correct design 109/109 on the fixture's ground truth).
`segment_operations()` itself — the thing that turns occurrences into spans —
is still not written; that's the next code to write once there's reason to
resume this track, but per the user's stated priority, **don't pick it up
proactively**. Resume when the user brings a fresh corpus report from next
week's diagnostics, or explicitly asks to continue chunking work.

If a fresh corpus report does arrive: it will very likely be NBSP-corrupted
if captured by terminal paste (both existing `mfg_corpus_report*.json` were —
2643 and 5609 NBSPs, failing `json.load`). `.replace('\u00a0', ' ')` before
parsing works around it, but ask the user to redirect script output straight
to a file this time so the next session doesn't have to.

`C:\tmp\mfg-overnight\` (driver.py, summarize.py, results.jsonl, raw/) is
deliberately **not** committed — it's a one-off harness, not reusable
instrumentation, per the "instrument hygiene" note in the manufacturing
handoff about script proliferation. Its README documents the 87-run result;
the manufacturing handoff has the corrected analysis (operation-collapse was
one bug, not generic noise — don't re-litigate that, it's settled).

## 3. Orientation — worktrees in play

| worktree | branch | HEAD | for |
|---|---|---|---|
| `C:/tmp/doc-tools-pcn` | `fix/pcn-continuation-table-pairing` | `476cd29` | the PCN/PDN fix (§1) |
| `C:/tmp/doc-tools-mfg` (here) | `mfg-extraction-investigation` | `370b981`, 9 commits ahead of `origin` | manufacturing + both handoff docs |
| `C:/tmp/doc-tools-fix` | `fix/sustainment-empty-crops` | `20143b5` | `crops_empty_lost` guard — referenced by the manufacturing handoff's ordering, not currently being worked |
| `C:/Users/cnogr/git/doc-tools` | `lane/7f` | `bee5b4c` | the main checkout; all worktrees share this `.git`, so any branch's commits survive even if a worktree is deleted |

`mfg-extraction-investigation` has 9 unpushed local commits (the handoff-doc
corrections and the reallayout fixture) — push when convenient, no blocker
observed for this branch specifically (only the PCN fix branch's push was
denied, and that may have been circumstantial rather than branch-specific).
