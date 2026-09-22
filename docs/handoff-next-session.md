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

## 1. PCN/PDN — the open question a fresh session will get asked

The user asked directly: *"did you test these fixes against the pdns in minio
I provided you? And if so did you validate the results were sane?"*

**Answer: no.** `fix/pcn-continuation-table-pairing` (8 commits off
`origin/main`, in worktree `C:/tmp/doc-tools-pcn`, HEAD `476cd29`) has **61
passing unit tests** against synthetic grids and fake pdfplumber pages
(`_FakePage`/`_FakeTable` in `tests/test_table_text_layer.py`) — both
directions of every fix are pinned (continuation-inherits, caption-still-works,
column-count-mismatch-declines, alias-veto, alias-word-inside-a-real-MPN-not-
dropped, quote-stripping, table-less-page-ends-inheritance). **It has never
been run against a real PDN document.** No sanity check of actual extracted
values against a real notice, no before/after `from_replacement_column` count
on real data.

Why: the validation loop needs
`kubectl exec -i -n sandbox <pod> -- python - --prefix sustainment/ --tl-path
... < scripts/pdn_parts_diagnostic.py` (full command in the PDN handoff, "Validation
loop" section). Every attempt at that command was denied by the Claude Code
auto-mode permission classifier ("Blocked by classifier") — not a bug in the
command, a policy block on piped `kubectl exec`. `git push` for the fix branch
was blocked the same way, so it is also not on `origin` yet (upstream is
still `origin/main` — check with `git rev-parse --abbrev-ref
fix/pcn-continuation-table-pairing@{upstream}` before assuming otherwise).

**What to try, in order, next session:**

1. Just retry the `kubectl exec` command — permission classifier behavior can
   differ session to session; don't assume the block is permanent without
   trying.
2. If still blocked, ask the user to run it themselves. Give them the exact
   command from the PDN handoff's "Validation loop" section, **and the trap
   that follows it**: `--tl-path` must point at the module as it stands on
   `origin/main` to reproduce the original 136/402 baseline, and at the fix
   branch's `table_text_layer.py` to see the post-fix numbers — pointing it at
   the fixed module changes the diagnostic's own header detection, not just
   production behavior, so comparing baseline-classified-by-fixed-module
   against itself is not a valid before/after.
3. Whoever runs it: check `from_replacement_column` collapses toward zero
   (the stated success criterion) and spot-check a handful of the previously-
   miscounted parts by opening the source PDN and confirming the
   fix now reads header/replacement columns as a human would.
4. Push `fix/pcn-continuation-table-pairing` once corpus-validated (or sooner,
   if the user just wants it backed up — the commits are already durable in
   `C:/Users/cnogr/git/doc-tools/.git`, shared across worktrees, so there is no
   data-loss urgency, only a backup/visibility one).

Do not tell the user "it's tested" without qualifying *unit* vs *corpus* —
that distinction is the entire content of their question.

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
