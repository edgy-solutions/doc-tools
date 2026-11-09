# `tools/` — operator scripts for a roll

Five scripts that are run **by hand, from the repo root**, around a pin bump or
a release roll. They lived in `scratchpad/` until 2026-11-08, which was wrong in
two ways: the scratchpad is untracked, so the only copy of a procedure the lane
depends on was one `rm` from gone; and a `.py` file at the scratchpad root
**shadows a real package** when a harness is run from there.

Nothing here is imported by `doc_tools/`, `scripts/` or `tests/` — verified by
grep, and worth keeping true. These are operator tools, not library code.

| Script | What it does |
|---|---|
| `preroll_diff.py` | Renders the values diff for a roll: `helm get manifest` (live) against `helm template` (the tree), redacting **both sides** before any output. **The sanctioned way to see what a roll changes** — do not run `helm get values` or `helm get manifest` wholesale instead. |
| `drift_check.py` | Reads helm user-supplied values as JSON on stdin and prints the structure. Only `image.digest` and `corpusGate.expectImage` print in full; every other leaf is `len=N sha256:XXXXXXXX`. |
| `patch_expect_ca3e7d83.py` | Roll 2 of the `ca3e7d83` pin: writes `corpusGate.expectImage` **from a reading of the running pods**. Applied 2026-11-08 (release rev 59). |
| `patch_expect_2bf85719.py` | The same write for the earlier `2bf85719` roll. Kept as the second worked example: two of these together show what is procedure and what was per-roll. |
| `read_index.py` | Reads the pin index. Was `scratchpad/pinread/read_index.py`. |

## The two rules these encode

**1. Print a length and a hash prefix, never a secret value.** A secret's
presence or equality is shown as `len=N sha256:XXXXXXXX` (first 8 hex). This is
not hypothetical: a drift script in this repo once printed three live
credentials into a transcript, and a transcript is not editable.
`drift_check.py` redacts every leaf but the two digests, and `preroll_diff.py`
redacts both sides of the diff before anything reaches the output.

**2. `expectImage` is READ-THEN-WRITE.** A pin bump is **two** digests, and the
roll is one roll in **two applies**: bump `image.digest`, apply, read the pods,
write `corpusGate.expectImage` from that reading, apply again. Ruled
2026-11-07: the second write is *part of the roll*, not a follow-up, so the roll
is not finished until the second apply lands.

The value is taken off `.status.containerStatuses[*].imageID` and **never
copied from `image.digest`**. The two being equal is the result being asserted,
not the source of the value. Nothing automatic keeps them in step — no test and
no CI job compares them, because the Job that would is the one being checked.

The `patch_expect_*` scripts refuse rather than guess: no pod reading on disk,
more than one distinct imageID, pods disagreeing with `image.digest`, or an
anchor line not matched exactly once each stop the write with the values file
untouched.

## Two things that will waste your time

- **`kubectl` and `helm` have no `current-context` on this workstation.** A bare
  invocation targets `localhost:8080` and reports *connection refused*, which
  reads exactly like a down cluster. `preroll_diff.py` passes **no**
  `--kube-context` (unlike `scratchpad/roll_diff.py`, which hardcodes `edge`),
  so give it one — prepend a credential-free overlay holding nothing but
  `current-context: edge` to `KUBECONFIG`, rather than copying the kubeconfig
  or mutating the user's.
- **Run these from PowerShell**, not a POSIX shell: MSYS rewrites slash-bearing
  `kubectl` arguments. Transient outputs (a pod reading, a render log) belong in
  `scratchpad/`, which is why the paths inside these scripts still point there.
