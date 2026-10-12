# Pin b18d7dc4: parts are 522/522 in all three fires, and the crop seal is the only red

Report, lane 7f, 2026-10-12. Closes the order
*"build the next pin as one unit: #107 + source_sha256 re-key with the 522
denominator + gt_parts == distinct_parts assertion + TI mfr alias set + the
field-label-as-value rejection at the header boundary. Merge, build, pin, fire,
publish."*

Merge ✅ (#107, #109) · build ✅ · pin ✅ · roll ✅ · fire ✅ · publish — this PR.

## The pin

    image.digest           sha256:d16b4402... -> sha256:b18d7dc4678e72daaf53e6a8017c52232903c60ce8ba24fd33a040b1ee2b973b
    corpusGate.expectImage pods=...d16b4402... -> pods=...b18d7dc4...

Both moved in the same edit, because a pin bump has two digests and helm reads
the working tree. `b18d7dc4` is 8725e04 (#109), which also carries #107 and #63.

**`measured_image == the chart pin`**, confirmed from the committed report, not
assumed: `image_identity.measured_digest` is `sha256:b18d7dc4...`, `checked:
true`, and the one comparison (`pods`) matches. Either side of that equality can
be stale independently, so it is quoted from the report rather than inferred
from the roll having succeeded.

## Verdict: FAIL — and it is one condition, fully named

| | 06:25Z — d16b4402, /924 | 20:56Z — b18d7dc4, /522 |
|---|---|---|
| parts | 915/924 — 1 spurious, 9 missing, 1 malformed | **522/522 — 0 spurious, 0 missing, 0 malformed** |
| per-notice defects | TI 0/9 | **none — no notice lost, gained or malformed a part** |
| Diodes FULLGREEN `doc_id` disagreement | BLOCKING | gone, dissolved with the duplicate |
| TI `mfr` misformatted, 3 of 3 fires | BLOCKING | gone |
| scored entries vs documents | 11 over 10 | **10 over 10** |
| remaining blocker | — | crop seal, IDT p1 |

Three fires, all three `exit 1`, all three `522/522` with every residual zero
and `seal_checked: true`. Elapsed 3237.9 / 3071.1 / 3044.9 s.

**So #107 and #109 delivered what they were built for.** The two reds the pin
block predicted it would clear are cleared, and the denominator moved
`10 docs / 11 entries / 924 gt / 522 distinct` → `10 / 10 / 522 / 522`, with
`gt_parts == distinct_parts` now holding by assertion rather than by luck.

A caution the pin block already carried and the result does not retire: the TI
`mfr` misformat was measured at **5 of 6**, not deterministically, so three
clean fires is weaker evidence than it looks. The alias set is the right fix;
one night does not prove it.

### The single blocking condition

    FAIL IDT_PDN_OV-19-05.pdf p1 box=(50.8, 117.3, 553.1, 505.7) cut_by=top,bottom

`verdict` is computed as `pass if (fires_ok and not blocking)`, and `blocking`
holds exactly the three fire exits — so this one seal failure is the whole of
the red.

**It is pre-existing and deterministic, measured rather than assumed.** The
identical line — same file, same page, same box to one decimal, same
`cut_by` — appears across **six fires, two pins, two code states**. This
morning's pod logs were still retrievable and carry it too.

I formed the hypothesis that the four-edge crop seal newly revealed it and
**disproved it**: the four-edge seal landed in `c0a5a0d` on 2026-09-27, 135
commits back. It was not revealed tonight; it was *masked* this morning by TI's
0/9, and tonight is simply the first run where it is the sole surviving cause.

**It costs zero parts.** IDT scores 17/17. The clipping cuts the rendered crop
through the glyphs on the top and bottom edges; the parts for that notice still
come out whole. This is the shape already ruled pin-able: known, deterministic,
fully explained, and not a parts regression.

It goes to the backlog as its own item rather than being exempted. Per the
standing correction, a real extraction weakness is not gate noise.

### `strict_verdict` is also FAIL, for a second and different reason

`strict_verdict` additionally requires `header_exit == 0`. Header agreement
exits 1 on one notice:

    TYC-PCN-24-210412.pdf  doc_level_ltb_date_source: '-2024' | '-2024\n[Unca' | '-2024'

This is the known truncation, **reconfirmed tonight**: the field is being cut to
its last five characters, and in one fire of three it keeps a fragment of the
following line. It is a *source-attribution* field, not the date — TYC's LTB
date itself is closed at 2024-06-06 — so it does not move a score. Also
backlog, not exempted.

Header correctness is 7/9 exact in all three fires, `clean: true`, and "every
established header field matched the page in every fire."

## What this PR carries, and why together

`charts/doc-tools/values-sandbox.yaml` (the pin) **and** the report measured on
it, in one commit. Not a convenience: the required `corpus-gate` check compares
the committed report's `corpus` block against ground truth on four keys, and the
check is path-gated to `^charts/` or `^docs/corpus-gate/`. A code-only PR is
filtered out of it and cannot satisfy it; a chart-only PR moves the denominator
away from the last committed report and fails it. The two must land together.

Three report artifacts come across from the publisher branch unchanged
(`latest.json` plus the 09:28Z and 20:55Z reports). **The publisher branch
`corpus-gate/nightly` can never merge** — it is never rebased, so its PR (#110)
conflicts permanently. Carrying its output in a PR off `main` is how a report
reaches `main` at all; #110 stays open and is not the publication.

`test_verdict_is_pass` will be red on this PR. By its own docstring it is **not
part of the required check** — it is selected by the advisory
`corpus-gate-verdict` job, which runs only on a `charts/**` diff. That is the
standing order "red blocks the next pin" working as designed: this pin is
landing on a named, deterministic, zero-parts-cost red, and the *next* pin is
what it blocks.

## Evidence discipline

Fire logs were read inside the sandbox pod; no YAML was dumped from the
secret-bearing CronJob and no credential was materialized locally. The chart
values diff is in this PR's diff and was reviewed before the roll. All Python
ran through this repo's venv.
