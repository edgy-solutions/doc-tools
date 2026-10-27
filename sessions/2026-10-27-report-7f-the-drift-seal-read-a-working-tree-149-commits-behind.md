# Report — lane 7f, 2026-10-27 (late): the cross-repo drift seal was reading a working tree 149 commits behind, and it was hiding a live drift as well as inventing a dead one

Queue item: **Packet B item 1**, the pinned drift seal. Shipped as **#181, a
draft that is red on purpose.** Also in this block: #180 (`failed:concept_parse`),
a correction to a claim I made about the build-skip allowlist, and the
`corpus-gate` guard warning that claimed teeth the verdict job does not have.

---

## 1. The seal, and what reading a working tree cost

`tests/test_overlay_kind_drift.py` resolved the platform's content-kind overlay
to `../invincible-agent/policy/overlays/openddil-lab/content_kinds` — **the
sibling repo's working tree.** On this machine that tree sits on
`lane/ca-resolve-instance-adoption`, **149 commits behind `origin/master`**
(the memory from 2026-10-25 said 91; it has drifted further since). So the seal
has been reporting another lane's in-progress branch as the platform's registry.

Both legs measured today, against the pin `4a4cf47c` (= their `origin/master`):

| | measured |
|---|---|
| the red it was reporting | `doors-export` — **not real**; it agrees at `master` |
| the drift that IS real | **`course`**: our `passes` carry `render.pages`, the overlay's do not |
| the seal at the pin | 6 passed, 1 failed |
| one-sided kinds at the pin | ours only `cad`, `document`, `dxf`, `step-ap242`; overlay only `maintenance-fault-event` |

The second row is the part worth stating plainly: **the stale tree was not only
fabricating a red, it was concealing a real divergence.** `render.pages` landed
on our generated `course` row in `ac661e4` (2026-10-25, #164, lane tr step e),
which is on `main`; the 149-behind tree has it on neither side, so the gap was
invisible. A green run proved nothing either, because which commit it measured
depended on what someone else happened to have checked out.

And the docstring's item 2 — which named `work-instruction`, `pdf`,
`doors-export`, `engineering-document` as ours-only — was **stale**. At the pin
the overlay has all four.

## 2. What #181 changes

Branch `7f/pinned-overlay-drift-seal`, `7ffb8d6`, cut off `main` (a PR stacked
on another branch dispatches no CI in this repo at all). Three files.

- **`tests/pins/invincible-agent.ref`** (new) — one 40-hex sha, written as
  bytes with a bare `\n`, because a `write_text` CRLF has broken a pinned sha
  in this repo before. An arm asserts `b"\r" not in` the file.
- **Resolution, in order:** the explicit `IAGENT_CONTENT_KIND_OVERLAY_DIR`,
  whose `IAGENT_CONTENT_KIND_OVERLAY_REF` must **equal** the pin or the seal
  fails naming both shas — a job that fetched the wrong commit is caught rather
  than believed; then a sibling repo's **pinned commit objects** via
  `git archive` into a scratch dir, never its files; then nothing, which
  **FAILS under CI** and skips only locally, keeping the "NOT satisfied, only
  unrun" sentence. A seal that skips in the one place it is meant to run is the
  defect this removes.
- **CI fetches the pin** in the `tests` job: validate 40-hex, then
  `actions/checkout` of `edgy-solutions/invincible-agent` at that sha into
  `.overlay-pin`, then both env vars on the pytest step. The repo is **public**
  (`gh api` → `visibility=public`), so no PAT is involved. No
  `continue-on-error`.
- **The one-sided SET is now sealed** (`OURS_ONLY` / `OVERLAY_ONLY`, a reason
  per entry), so a *new* one-sided kind reds while the known registration gap
  does not — and the failure says the decision is the platform's to take, never
  something to make green by deleting a row here.
- Six arms for the resolver's own machinery (pin parsing; a short sha, a branch
  name, an empty and a comment-only pin each refused; the REF mismatch; a
  non-directory DIR; nothing-resolvable failing under `GITHUB_ACTIONS` and
  skipping without it).

The build-skip allowlist is deliberately untouched: `tests/pins/` is not
`docs/`, which is right — a pin bump must build.

## 3. Verified twice, and the second one is the one that mattered

**Locally**, from PowerShell on the venv interpreter:
`1 failed, 2275 passed, 13 skipped, 16 deselected, 1 xfailed in 101.56s`.

**In CI** (run `40503207475`, `tests` job), which is the part a local run
cannot prove: the pin-read step and the cross-repo checkout both succeeded on
`GITHUB_TOKEN` alone, and the suite ran to completion —
`1 failed, 2286 passed, 13 skipped, 7 deselected, 1 xfailed in 48.75s`. The
single failure is `course`/`render.pages`, **not** the resolver's "cannot be
resolved" path. So the seal reads the pinned commit in CI, and a missing fetch
would fail loudly rather than skip.

A red on `course` rather than `doors-export` is the acceptance signal, not a
regression. `overlay_rows` in that failure contains `maintenance-fault-event`,
which is independent confirmation the rows came from the pinned commit.

## 4. Why #181 is a draft, and what unblocks it

Merging it would hand doc-tools a red in the required `tests` job **for a row
another repo owns** — exactly what the seal's own docstring warns against.

Per the 2026-10-24 ownership ruling the platform owns what a kind IS and
doc-tools owns what it RUNS (`passes`); the overlay **mirrors** `passes` and
says so in its own header comment, and our row is *generated* from
`KIND_MAPPING` with `tests/test_kind_registry.py` red on hand edits. So there
is no version of this we can make green on our side without lying about what
runs, and **#181 does not touch `registry/content_kinds/course.yaml`.**

Packet **placed, not committed** (their tree, per the fleet convention) at
`invincible-agent/sessions/2026-10-27-packet-to-lane-01-from-doc-tools-7f-the-course-overlay-row-is-one-pass-behind-and-the-drift-seal-is-about-to-see-it.md`,
asking lane 01 to append `- render.pages` to the overlay row and offering to
open that one-line PR ourselves if they would rather. Re-checked at the time of
writing: their `origin/master` is still `4a4cf47c` and still has no
`render.pages`.

When it lands: bump the pin here in the one-line PR carrying the drift report,
undraft #181, and both repos go green together. **If it stalls, this is the
architect's to rule** — we are not going to make a real drift green to clear a
board.

## 5. Also in this block

- **#180 — `failed:concept_parse`.** A per-chunk `plugin.augment` raise now
  posts `failed:concept_parse` as the run's last act and raises, so the run
  FAILS. (There is no `partial` ingest stage: `iagent_mesh` 0.9.8 exports
  `("received","extracting","review","promoted","rejected","failed")`, so "never
  success" means fail, per #166's precedent.) Ordering: `graph_write`/
  `link_write` beat it; it beats `extraction_empty`, because a raised
  augmentation is the cause and zero rows the symptom. Own branch off `main`,
  11 new arms. Packet to tr placed and committed (`798263d`) with the pin-first
  re-ingest order.
- **A correction.** I claimed adding `sessions/` to the build-skip allowlist
  would stop sessions-only commits dispatching a build. **It does not, on a
  PR.** The `changes` job diffs `base.sha...head.sha` — the whole PR against
  base — never the pushed commit, so a sessions-only commit on a code-bearing
  PR still builds. Measured: pushing `798263d` dispatched `build-and-push` as
  normal. The change itself is still correct; my claim about its reach was not.
  `cdf2478`'s commit message carries that overstatement and was left as pushed.
- **`998fa1c`:** the `corpus-gate` guard's measured-FAIL
  warning claimed it "still blocks the next pin through the
  `corpus-gate-verdict` job". It does not: `corpus-gate` is the only required
  context, and on a pin bump `test_verdict_is_pass` skips itself because moving
  the pin moves the chart's digest away from the last report's measured digest.
  Both reasons are now named in the file.

## 6. Queue, unchanged otherwise

1. **Fire a pre-roll Job at sandbox** — still never done; still the only thing
   that closes the red window between a roll and its report PR. Blocked on a
   candidate digest: a green `build-and-push` on a PR pushes no image.
2. **Land #167** → pin bump → the Neo4j migration dry run **as a pod Job**
   (`NEO4J_*` is pod-env only; counts arrive a pin bump later).
3. **Land #180** → pin bump → tr re-ingests `_p132`/`_p102` and re-goldens.
4. The batch fixture chain (Packet B item 2's four rulings).
5. #181 — blocked on lane 01, not on us.

— lane 7f
